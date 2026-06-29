import argparse
from pathlib import Path
import random
import json
from typing import Any
from datetime import datetime
from time import time
from osgeo import gdal, ogr


DEFAULT_OUTPUT = Path("benchmark_output")
DEFAULT_REPORT = Path("benchmark.json")


def _get(dict: dict | list, *keys, default=None) -> Any:
    for key in keys:
        try:
            dict = dict[key]
        except (KeyError, IndexError):
            return default
    return dict


def run(
    dsn: str,
    output_dir: Path,
    report: Path,
    overwrite: bool = False,
    count: int | None = None,
    shuffle=False,
    include: str | None = None,
    timeout: int | None = None,
    retry: bool = False,
) -> None:
    ogr.UseExceptions()

    ds = ogr.Open(f"SDEORAESRI:{dsn}")
    if ds is None:
        raise RuntimeError("Failed to open datasource")

    # collect all layers
    layers = []
    for layer in ds:
        layers.append(layer.GetName())
    ds.Close()
    print(f"Found {len(layers)} layers")

    if shuffle:
        random.shuffle(layers)
    if count:
        layers = layers[:count]
    if include:
        layers = [lyr for lyr in layers if include in lyr]

    print(f"Will export {len(layers)} layers")

    output_dir.mkdir(exist_ok=True)
    report.parent.mkdir(exist_ok=True)

    if report.exists():
        results = json.load(report.open("r"))
        print(f"Continuing with {len(results)} items")
    else:
        results = {}

    output = None
    try:
        for layer in layers:
            print(
                f"Started {layer} at {datetime.now():%Y-%m-%d %H:%M:%S}... ",
                end="",
                flush=True,
            )
            if layer in results:
                prev_res = results[layer]["status"]
                prev_val = results[layer]["duration"]
                if overwrite:
                    pass
                elif prev_res == "SUCCESS":
                    print("already done")
                    continue
                elif prev_res == "TIMEDOUT" and timeout and int(prev_val) >= timeout:
                    print(f"already timedout (set timeout >{prev_val} to retry)")
                    continue
                elif prev_res == "ERROR" and not retry:
                    print("already errored (run with --retry to retry)")
                    continue

            output = output_dir.joinpath(f"{layer}.fgb")
            if output.exists():
                output.unlink()

            # Layer DSN
            lyr_dsn = f"SDEORAESRI:{dsn}|{layer}"

            # Get metadata
            lyr_info = _get(gdal.VectorInfo(lyr_dsn, format="json"), "layers", 0)

            # Extract data
            status = None
            duration = None
            debug = None

            t0 = time()
            did_timeout = False

            def timeout_callback(complete, message, data):
                nonlocal did_timeout
                did_timeout |= timeout is not None and (time() - t0 >= timeout)
                return not did_timeout

            try:
                gdal.VectorTranslate(str(output), lyr_dsn, callback=timeout_callback)
                status = "SUCCESS"
                duration = time() - t0
            except Exception as e:
                if did_timeout:
                    status = "TIMEDOUT"
                    duration = timeout
                else:
                    status = "ERROR"
                    duration = time() - t0
                    debug = str(e)
                if output and output.exists():
                    output.unlink()
            print(f"{status} in {duration:.2f}s")
            results[layer] = {
                "status": status,
                "duration": duration,
                "debug": debug,
                "features_count": _get(lyr_info, "featureCount"),
                "fields_count": len(_get(lyr_info, "fields", default=[])),
                "geom_type": _get(lyr_info, "geometryFields", 0, "type"),
                "size_mb": float(_get(lyr_info, "metadata", "", "SIZE_MB", default=0)),
            }
            json.dump(results, report.open("w"), indent=2)

    except KeyboardInterrupt:
        print("interrupted!")
        if output and output.exists():
            print("cleaning up interrupted export")
            output.unlink()

    print("Done !")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dsn")
    parser.add_argument("--count", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--include", type=str)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()
    run(
        dsn=args.dsn,
        output_dir=args.output,
        report=args.report,
        overwrite=args.overwrite,
        count=args.count,
        shuffle=args.shuffle,
        include=args.include,
        timeout=args.timeout,
        retry=args.retry,
    )
