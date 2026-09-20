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
    if not 1 <= args.forecast_hours <= 120:
        parser.error("--forecast-hours must be between 1 and 120")

    work = Path("/workspace/outputs/ww3") / args.region
    work.mkdir(parents=True, exist_ok=True)
    grid_prefix = f"s3://{args.s3_bucket}/static/native-marine/{args.region}/ww3-grid/"
    forcing_prefix = f"s3://{args.s3_bucket}/forcing/ww3/{args.run_date}/{args.region}/"
    wrf_prefix = f"s3://{args.s3_bucket}/predictions/{args.run_date}/runs/{args.run_id}/wrf/"
    output_prefix = f"s3://{args.s3_bucket}/predictions/{args.run_date}/runs/{args.run_id}/{args.region}/"
    run(["aws", "s3", "sync", grid_prefix, str(work), "--only-show-errors"])
    # NOTE: forcing is ALWAYS regenerated fresh, never reused from a prior
    # run's cache. forcing_prefix is keyed by (run_date, region) only, not
    # run_id or forecast_hours -- caching by wind.nc-exists here previously
    # caused a real bug: a short canary run and a later full-length run on
    # the same run_date silently reused the canary's short forcing, giving
    # a false "SUCCEEDED" on a run that actually simulated a fraction of
    # the requested forecast length. Regeneration is cheap (~seconds), so
    # there's no real cost to always doing it fresh.
    wrf_dir = Path("/workspace/inputs/wrf")
    generated = Path("/workspace/inputs/ww3")
    run(["aws", "s3", "sync", wrf_prefix, str(wrf_dir), "--exclude", "*", "--include", "wrfout_d02_*", "--only-show-errors"])
    run(["python3", "/app/scripts/prepare_ww3_wind_from_wrf.py", "--wrf-dir", str(wrf_dir), "--output-base-dir", str(generated), "--regions", args.region])
    region_forcing = generated / args.region
    run(["aws", "s3", "sync", str(region_forcing), forcing_prefix, "--only-show-errors"])
    run(["cp", "-r", f"{region_forcing}/.", str(work)])
    for required in ("mod_def.ww3", "wind.nc", "ww3_prnc.nml", "ww3_shel.nml", "ww3_ounf.nml"):
        path = work / required
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Missing immutable WW3 input: {path} (source {grid_prefix} or {forcing_prefix})")
    run(["ww3_prnc"], cwd=work)
    run(["mpirun", "--allow-run-as-root", "--use-hwthread-cpus", "-np", str(args.mpi_ranks), "ww3_shel"], cwd=work)
    run(["ww3_ounf"], cwd=work)
    netcdf_files = [path for path in work.glob("*.nc") if path.name != "wind.nc"]
    if not netcdf_files or not all(path.stat().st_size > 0 for path in netcdf_files):
        raise RuntimeError("WW3 completed without a NetCDF output")
    (work / "WW3_SUCCESS").write_text("status=SUCCESS\n", encoding="utf-8")
    run(["aws", "s3", "sync", str(work), output_prefix, "--only-show-errors"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
