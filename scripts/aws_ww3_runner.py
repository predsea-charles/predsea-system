#!/usr/bin/env python3
"""Run one regional WW3 forecast from immutable S3 grid/forcing inputs."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["ww3"], default="ww3")
    parser.add_argument("--region", required=True)
    parser.add_argument("--forecast-hours", type=int, default=72)
    parser.add_argument("--mpi-ranks", type=int, default=24)
    parser.add_argument("--s3-bucket", required=True)
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.forecast_hours != 72:
        parser.error("AWS WW3 production runs are fixed at 72 hours")

    work = Path("/workspace/outputs/ww3") / args.region
    work.mkdir(parents=True, exist_ok=True)
    grid_prefix = f"s3://{args.s3_bucket}/static/native-marine/{args.region}/ww3-grid/"
    forcing_prefix = f"s3://{args.s3_bucket}/forcing/ww3/{args.run_date}/{args.region}/"
    output_prefix = f"s3://{args.s3_bucket}/predictions/{args.run_date}/runs/{args.run_id}/{args.region}/"
    run(["aws", "s3", "sync", grid_prefix, str(work), "--only-show-errors"])
    run(["aws", "s3", "sync", forcing_prefix, str(work), "--only-show-errors"])
    for required in ("mod_def.ww3", "wind.nc", "ww3_prnc.nml", "ww3_shel.nml"):
        path = work / required
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Missing immutable WW3 input: {path} (source {grid_prefix} or {forcing_prefix})")
    run(["ww3_prnc"], cwd=work)
    run(["mpirun", "--allow-run-as-root", "--use-hwthread-cpus", "-np", str(args.mpi_ranks), "ww3_shel"], cwd=work)
    run(["ww3_ounf"], cwd=work)
    netcdf_files = list(work.glob("*.nc"))
    if not netcdf_files:
        raise RuntimeError("WW3 completed without a NetCDF output")
    (work / "WW3_SUCCESS").write_text("status=SUCCESS\n", encoding="utf-8")
    run(["aws", "s3", "sync", str(work), output_prefix, "--only-show-errors"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
