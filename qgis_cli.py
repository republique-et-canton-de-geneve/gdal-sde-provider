import os
import time
import argparse
import pathlib

from qgis.core import QgsApplication, QgsVectorLayer, QgsFeatureRequest, QgsRectangle


def main(connection_string):

    os.environ["GDAL_PYTHON_DRIVER_PATH"] = str(
        pathlib.Path(__file__).parent.joinpath("driver")
    )

    qgs = QgsApplication([], False)
    qgs.initQgis()

    layer = QgsVectorLayer(f"SDEORAESRI:{connection_string}")

    if not layer.isValid():
        raise Exception("Layer failed to load!")

    request = QgsFeatureRequest(
        QgsRectangle(2501064.4, 1116447.5, 2502048.4, 1116884.7)
    )
    t0 = time.time()
    load_bbox_features = [i for i in layer.getFeatures(request)]
    print(
        f"Loaded bbox features ({len(load_bbox_features)}) in {time.time() - t0:.5f}s"
    )

    t0 = time.time()
    load_all_features = [i for i in layer.getFeatures()]
    print(f"Loaded all features ({len(load_all_features)}) in {time.time() - t0:.5f}s")

    qgs.exitQgis()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Helper to quickly test the driver in PyQGIS for faster iterations than using the GUI"
    )
    parser.add_argument(
        "connection_string",
        help="Of shape `SDEORAESRI:user/password@service|schema.tablename`",
    )
    args = parser.parse_args()
    main(args.connection_string)
