# gdal: DRIVER_NAME = "SDEORAESRI"
# gdal: DRIVER_SUPPORTED_API_VERSION = [1]
# gdal: DRIVER_DCAP_VECTOR = "YES"
# gdal: DRIVER_DMD_LONGNAME = "Custom Python provider for reading vector data from ESRI Oracle SDE"

import pyproj
import oracledb
from datetime import date, datetime, time
from functools import cached_property
from gdal_python_driver import BaseDriver, BaseDataset, BaseLayer


# have oracledb return LOB and similar as str or bytes instead of LOB locators
# see: https://python-oracledb.readthedocs.io/en/latest/api_manual/defaults.html#oracledb.Defaults.fetch_lobs
oracledb.defaults.fetch_lobs = False


DRIVER_PREFIX = "SDEORAESRI:"
DB_GEOMTYPE = "ST_GEOMETRY"
DBTYPE_TO_OGRTYPE: dict[tuple[str, int | None], str] = {
    ("NVARCHAR2", None): "String",
    ("CHAR", None): "String",
    ("NCLOB", None): "String",
    ("NUMBER", 0): "Integer",
    **{("NUMBER", i): "Float" for i in range(1, 16)},
    ("DATE", None): "Date",
    ("TIMESTAMP(6)", 6): "DateTime",
    # "???": "Boolean",
    # "???": "Integer16",
    # "???": "Integer64",
    # "???": "Real",
    # "???": "Float",
    # "???": "Binary",
    ("BLOB", None): "Binary",
    # "???": "Time",
    # "???": "DateTime",
}
GEOMSUBTYPE_TO_OGRGEOM = {
    # Unsure why, these don't seem to be properly taken into account, yielding these errors
    # > ICreateFeature: Mismatched geometry type. Feature geometry type is
    # > Polygon, expected layer geometry type is Multi Polygon
    # For some reason it seems to work better by just falling back to "Geometry"
    1: "Geometry",  # Point
    2: "Geometry",  # MultiPoint
    3: "Geometry",  # MultiLineString
    4: "Geometry",  # MultiPolygon
    9: "Geometry",  # Unknown
    None: "Unknown",  # Seems some layers have NONE ?
}


def execute_as_dicts(cursor, sql, params=None):
    """Helper to iterate cursor as a dict

    See https://python-oracledb.readthedocs.io/en/latest/user_guide/sql_execution.html#rowfactories"""
    cursor.execute(sql, params)
    columns = [col.name for col in cursor.description]
    cursor.rowfactory = lambda *args: dict(zip(columns, args))
    while True:
        row = cursor.fetchone()
        if row is None:
            break
        yield row


class Layer(BaseLayer):
    def __init__(self, connection, name):
        self._connection = connection

        self._owner, self._table = name.split(".", maxsplit=1)

        self.name = name
        self.fid_name = "OBJECTID"

        # optional
        self.metadata = {}

        # uncomment if __iter__() honour self.attribute_filter / self.spatial_filter
        # self.iterator_honour_attribute_filter = True
        self.iterator_honour_spatial_filter = True
        # self.feature_count_honour_attribute_filter = True
        # self.feature_count_honour_spatial_filter = True

    @cached_property
    def geometry_fields(self):
        geometry_fields = []
        with self._connection.cursor() as cursor:
            sql = """
            SELECT SPATIAL_COLUMN, AUTH_SRID, SRTEXT, i.DATASETSUBTYPE2
            FROM SDE.LAYERS lyr
            LEFT JOIN SDE.SPATIAL_REFERENCES sr ON sr.SRID = lyr.SRID
            LEFT JOIN SDE.GDB_ITEMS i ON i.PHYSICALNAME = lyr.OWNER || '.' || lyr.TABLE_NAME 
            WHERE OWNER=:bind_owner AND TABLE_NAME=:bind_table
            """
            params = [self._owner, self._table]
            for row in execute_as_dicts(cursor, sql, params):
                # try to retrieve the projection
                try:
                    epsg = pyproj.crs.CRS.from_epsg(row["AUTH_SRID"]).to_epsg()
                except pyproj.exceptions.CRSError:
                    # print(f"invalid SRID: {row['AUTH_SRID']}")
                    try:
                        epsg = pyproj.crs.CRS.from_wkt(row["SRTEXT"]).to_epsg()
                    except pyproj.exceptions.CRSError:
                        # print(f"invalid PROJ WKT: `{row['AUTH_SRID'][:100]}`")
                        epsg = None
                # fallback for non-standard WKT PROJ
                if epsg is None and "CH1903+_LV95" in row["SRTEXT"]:
                    epsg = 2056

                geometry_fields.append(
                    {
                        "name": row["SPATIAL_COLUMN"],
                        "srs": f"EPSG:{epsg}" if epsg else None,
                        # type is optional for GDAL, but QGIS crashed if not set
                        "type": GEOMSUBTYPE_TO_OGRGEOM[row["DATASETSUBTYPE2"]],
                    }
                )
                # For now, we support just one geometry field
                break
        return geometry_fields

    @cached_property
    def fields(self):
        fields = []
        with self._connection.cursor() as cursor:
            sql = "SELECT COLUMN_NAME, DATA_TYPE, DATA_SCALE FROM ALL_TAB_COLUMNS WHERE OWNER=:bind_owner AND TABLE_NAME=:bind_table"
            params = [self._owner, self._table]
            for row in execute_as_dicts(cursor, sql, params):
                if row["DATA_TYPE"] == DB_GEOMTYPE:
                    continue
                type_key = (row["DATA_TYPE"], row["DATA_SCALE"])
                try:
                    db_type = DBTYPE_TO_OGRTYPE[type_key]
                except KeyError:
                    print(
                        f"warning: type `{type_key}` is not implemented ({self._table})"
                    )
                    db_type = None
                fields.append(
                    {
                        "name": row["COLUMN_NAME"],
                        "type": db_type,
                    }
                )
        return fields

    # Optional. Called when self.attribute_filter is changed by GDAL
    # def attribute_filter_changed(self):
    #     # You may change self.iterator_honour_attribute_filter
    #     # or feature_count_honour_attribute_filter
    #     pass

    # Optional. Called when self.spatial_filter is changed by GDAL
    # def spatial_filter_changed(self):
    #     # You may change self.iterator_honour_spatial_filter
    #     # or feature_count_honour_spatial_filter
    #     pass

    def test_capability(self, cap):
        if cap == BaseLayer.FastGetExtent:
            return True
        if cap == BaseLayer.StringsAsUTF8:
            return True
        # if cap == BaseLayer.FastSpatialFilter:
        #    return False
        # if cap == BaseLayer.RandomRead:
        #    return False
        if cap == BaseLayer.FastFeatureCount:
            return self.attribute_filter is None and self.spatial_filter is None
        return False

    def extent(self, force_computation):
        if self.attribute_filter is not None or self.spatial_filter is not None:
            raise NotImplementedError()

        if force_computation or not hasattr(self, "_extent"):
            with self._connection.cursor() as cursor:
                sql = "SELECT MINX, MINY, MAXX, MAXY FROM sde.layers WHERE owner=:bind_owner AND table_name=:bind_table"
                params = [self._owner, self._table]
                for row in execute_as_dicts(cursor, sql, params):
                    self._extent = [row["MINX"], row["MINY"], row["MAXX"], row["MAXY"]]
                    break
        return self._extent

    def feature_count(self, force_computation):
        if self.attribute_filter is not None or self.spatial_filter is not None:
            raise NotImplementedError()

        if force_computation or not hasattr(self, "_feature_count"):
            with self._connection.cursor() as cursor:
                sql = f"SELECT COUNT(*) AS COUNT FROM {self.name}"
                for row in execute_as_dicts(cursor, sql):
                    self._feature_count = row["COUNT"]
                    break
                else:
                    self._feature_count = 0
        return self._feature_count

    def __iter__(self):
        with self._connection.cursor() as cursor:
            cursor.arraysize = 1000

            # build the select column statement
            _fields = [fld["name"] for fld in self.fields]

            # if we have a geometry, add it to select statemetn (as WKT)
            _geom_fields = self.geometry_fields
            if _geom_fields:
                if len(_geom_fields) > 1:
                    print("WARNING: the driver only supports one geometry per layer")
                geom_field = _geom_fields[0]["name"]
                epsg = _geom_fields[0]["srs"]
                _fields.append(f"SDE.ST_ASBINARY({geom_field}) AS WKB_GEOM")
            else:
                geom_field = None
                epsg = "EPSG:4326"

            sql = f"SELECT {', '.join(_fields)} FROM {self.name} f"
            params = []
            if self.spatial_filter:
                sql = f"""
                WITH bbox AS ( SELECT SDE.ST_GEOMETRY(:bbox_wkt, :bbox_srid) AS geom FROM DUAL )
                {sql}
                CROSS JOIN bbox
                WHERE SDE.ST_INTERSECTS(SHAPE, bbox.geom) = 1
                """
                params.append(self.spatial_filter)
                params.append(int(epsg.split(":")[1]))

            for row in execute_as_dicts(cursor, sql, params):
                if geom_field:
                    geoms = {geom_field: row.pop("WKB_GEOM")}
                else:
                    geoms = None

                # cast date* types to iso
                for key, val in row.items():
                    if isinstance(val, (datetime, date, time)):
                        row[key] = val.isoformat()

                yield {
                    "type": "OGRFeature",
                    "id": row["OBJECTID"],
                    "fields": row,
                    "geometry_fields": geoms,
                    # "style": None,
                }


class Dataset(BaseDataset):
    def __init__(self, dsn):
        # we must connect with thick mode
        # (otherwise we get `DPY-3001: Native Network Encryption and Data Integrity is only supported in python-oracledb thick mode`)
        oracledb.init_oracle_client()

        # parse connection string
        dsn, _, table = dsn.partition("|")
        userpass, _, dsn = dsn.partition("@")
        user, _, password = userpass.partition("/")
        hostport, _, service_name = dsn.partition("/")
        host, _, port = hostport.partition(":")
        if service_name or port:
            conn = dict(
                user=user,
                password=password,
                host=host,
                port=port,
                service_name=service_name,
            )
        else:
            conn = dict(
                user=user,
                password=password,
                dsn=dsn,
            )

        self.connection = oracledb.connect(**conn)

        # get the list of layers
        sql = "SELECT PHYSICALNAME FROM SDE.GDB_ITEMS WHERE PHYSICALNAME "

        if table:
            sql += "= :bind_table"
            params = [table]
        else:
            sql += "LIKE '%.%'"
            params = None

        self.layers = []
        with self.connection.cursor() as cursor:
            for row in execute_as_dicts(cursor, sql, params):
                self.layers.append(Layer(self.connection, row["PHYSICALNAME"]))
        self.metadata = {}

    def close(self):
        self.connection.close()


class Driver(BaseDriver):
    def identify(self, filename, first_bytes, open_flags, open_options={}):
        return filename.startswith(DRIVER_PREFIX)

    def open(self, filename, first_bytes, open_flags, open_options={}):
        return Dataset(filename.removeprefix(DRIVER_PREFIX))
