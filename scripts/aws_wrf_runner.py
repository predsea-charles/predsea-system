#!/usr/bin/env python3
"""Run one bounded WRF forecast from immutable S3 forcing/static inputs."""
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
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--forecast-hours", type=int, required=True)
    parser.add_argument("--s3-bucket", required=True)
    args = parser.parse_args()
    if not 1 <= args.forecast_hours <= 72:
        parser.error("--forecast-hours must be between 1 and 72")

    forcing = Path("/workspace/inputs/ecmwf")
    geography = Path("/opt/WPS_GEOG")
    output = Path("/workspace/outputs/wrf")
    for path in (forcing, geography, output):
        path.mkdir(parents=True, exist_ok=True)

    run(["aws", "s3", "sync", f"s3://{args.s3_bucket}/forcing/ecmwf/{args.run_date}/", str(forcing), "--only-show-errors"])
    run(["aws", "s3", "sync", f"s3://{args.s3_bucket}/static/wrf/WPS_GEOG/", str(geography), "--only-show-errors"])
    if len(list(forcing.glob("ecmwf_*.grib2"))) < 2:
        raise FileNotFoundError("ECMWF pressure/surface GRIB2 inputs are missing")
    if not list(geography.glob("*/index")):
        raise FileNotFoundError("staged WPS geography is incomplete")

    start = f"{args.run_date}_00:00:00"
    end_hour = args.forecast_hours
    from datetime import datetime, timedelta
    end = (datetime.strptime(start, "%Y-%m-%d_%H:%M:%S") + timedelta(hours=end_hour)).strftime("%Y-%m-%d_%H:%M:%S")
    environment = os.environ.copy()
    environment.update({"START_DATE": start, "END_DATE": end, "GRIB_DIR": str(forcing), "RUN_DIR": str(output)})
    print(f"WRF window: {start} through {end}", flush=True)
    subprocess.run(["/opt/predsea/run_pipeline.sh"], env=environment, check=True)

    wrf_files = sorted(output.glob("wrfout_d02_*"))
    if len(wrf_files) != args.forecast_hours + 1:
        raise RuntimeError(f"expected {args.forecast_hours + 1} hourly wrfout_d02 files, found {len(wrf_files)}")
    prefix = f"s3://{args.s3_bucket}/predictions/{args.run_date}/runs/{args.run_id}/wrf/"
    (output / "WRF_SUCCESS").write_text("status=SUCCESS\n", encoding="utf-8")
    run(["aws", "s3", "sync", str(output), prefix, "--only-show-errors"])

    # Generate WW3 wind forcing while wrfout_d02 files are still local.
    # This uploads wind.nc + namelist files (~MB) to S3 so the WW3 job
    # can skip downloading the full ~68 GB of wrfout_d02 output.
    ww3_forcing_base = Path("/workspace/inputs/ww3_forcing")
    run([
        "python3", "/app/scripts/prepare_ww3_wind_from_wrf.py",
        "--wrf-dir", str(output),
        "--output-base-dir", str(ww3_forcing_base),
    ])
    for region_dir in sorted(ww3_forcing_base.iterdir()):
        if region_dir.is_dir():
            ww3_forcing_prefix = (
                f"s3://{args.s3_bucket}/forcing/ww3/{args.run_date}/{region_dir.name}/"
            )
            run(["aws", "s3", "sync", str(region_dir), ww3_forcing_prefix, "--only-show-errors"])
            print(f"Uploaded WW3 wind forcing for {region_dir.name} to {ww3_forcing_prefix}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
