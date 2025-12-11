import pathlib
import argparse
from pathlib import Path
import random
import subprocess
import json
from osgeo import ogr
from datetime import datetime

from time import time

DEFAULT_OUTPUT = Path(__file__).parent.joinpath("tmp_output")


def run(
    dsn: str,
    output_dir: Path,
    report: Path | None = None,
    overwrite: bool = False,
    count: int | None = None,
    shuffle=False,
    timeout: int | None = None,
    retry: bool = False,
) -> None:

    ds = ogr.Open(f"SDEORAESRI:{dsn}")
    if ds is None:
        raise RuntimeError("Failed to open datasource")

    # collect all layers
    layers = []
    for layer in ds:
        print(layer.GetName(), flush=True)
        layers.append(layer.GetName())
    ds.Close()

    if shuffle:
        random.shuffle(layers)
    if count:
        layers = layers[:count]

    output_dir.mkdir(exist_ok=True)

    report = report or output_dir.joinpath("report.json")
    print(report.absolute())
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
                prev_res, prev_val = results[layer].split(":", maxsplit=1)
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

            t0 = time()
            try:
                msg = "ABORTED:?"
                subprocess.check_output(
                    ["ogr2ogr", output, f"SDEORAESRI:{dsn}|{layer}"],
                    timeout=timeout,
                    stderr=subprocess.STDOUT,
                )
                msg = f"SUCCESS:{time() - t0:.2f}s"
            except Exception as e:
                if isinstance(e, subprocess.CalledProcessError):
                    msg = f"ERROR:{e.output.decode()}"
                elif isinstance(e, subprocess.TimeoutExpired):
                    msg = f"TIMEDOUT:{timeout}"
                else:
                    msg = f"ERROR:{e}"
                if output and output.exists():
                    output.unlink()
                continue
            finally:
                print(msg)
                results[layer] = msg
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
    parser.add_argument("--report", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--shuffle", action="store_true")
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
        timeout=args.timeout,
        retry=args.retry,
    )
