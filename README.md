# GDAL Oracle SDE POC

> [!caution]
> This is **work in progress** and for now still **highly experimental** (but working in some cases).

**Proof-of-concept** for a GDAL/OGR driver able to read vector data from an Oracle ESRI Geodatabase.

The goal is to make it possible to read such databases without requiring proprietary tools such as ArcPy or FME. Having this capability as an GDAL/OGR driver makes it possible to use in various contexts (standalone CLI, python, but also advanced software using GDAL such as QGIS or DuckDB).

If the POC is conclusive, the driver could be translated to C for better performance, or maybe (if deemed acceptable) upstreamed as a standard GDAL/OGR driver. Worth noting that [it seems](https://www.osgeo.org/foundation-news/gdal-ogr-3-2-0-is-released/?utm_source=chatgpt.com#:~:text=Removal%20of%20GDAL%20and%20OGR%20ArcSDE%20drivers) such a driver used to exist at some point in GDAL.

The code was adapted from the [Vector driver in Python implementation tutorial](https://gdal.org/en/stable/tutorials/vector_python_driver.html), following [this example](https://github.com/OSGeo/gdal/blob/master/examples/pydrivers/ogr_DUMMY.py).

## Quickstart command line

This quickstart assumes [OSGeo4W](https://download.osgeo.org/osgeo4w/v2/osgeo4w-setup.exe) is installed with at least the following packages: `gdal`, `python3-gdal`, `python3-pip` and `oci`.

Run the following commands from you `OSGeo4W Shell`.

```ps1
# all following commands must be run from this folder
cd C:\path_to_repo

# install python-oracledb
pip install oracledb

# set env var so GDAL finds drivers
set GDAL_PYTHON_DRIVER_PATH=%CD%\driver
```

We're set !

In the following examples, you can also provide `HOST:PORT?SERVICE` instead of `ALIAS`. You can also optionnaly filter by layer at provider level by specifying `|SCHEMA.TABLE`.

```ps1
# ensure GDAL finds the driver (you should see `SDEORAESRI -vector- (ro): Custom Python provider [...]` as output)
ogrinfo --formats | findstr /I "SDEORAESRI"

# get infos with ogrinfo
ogrinfo -json "SDEORAESRI:USER/PASSWORD@ALIAS" "SCHEMA.TABLE"

# convert a layer with ogr2ogr
ogr2ogr output.geojson "SDEORAESRI:USER/PASSWORD@ALIAS|SCHEMA.TABLE"
```

## Quickstart QGIS

> [!caution]
> Here this approach leads to crashes (unsure why at this point)
>
> In `Options > System`, add the custom environment variable `GDAL_PYTHON_DRIVER_PATH` with value `C:\...\gdal-sde-provider-poc\src`. Restart QGIS.

Then, from the `Add Vector`, add this as a `file`: `SDEORAESRI:USER/PASSWORD@ALIAS|SCHEMA.TABLE`

For quick tests, a pyQGIS script is included, run it with `python-qgis qgis_cli.py USER/PASSWORD@ALIAS|SCHEMA.TABLE`

## Benchmarks

The following command exports all available layers, and stores processing time and errors into `report.json`.

```ps1
python benchmarks\benchmark.py --timeout 30 "USER/PASSWORD@ALIAS"
```

## Roadmap

For now, this is just a POC with no official support. These are the possible next steps:

- fix crashes when used from within QGIS
- test with more data and adapt accordingly (single/multi geometries, arcs, ensure no precision loss, etc.)
- [rewrite the driver in C](https://gdal.org/en/stable/tutorials/vector_driver_tut.html) for better performance
- MS SQL variant
- consider integration in GDAL
