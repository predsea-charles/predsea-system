#!/usr/bin/env python3
"""
PredSea WW3 NetCDF Post-Processor
Converts raw binary WW3 grid output (out_grd.ww3) into standardized NetCDF files (ww3_forecast.nc).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
import xarray as xr


def build_ounf_input() -> str:
    """Return a complete traditional ww3_ounf input deck for this forecast."""
    return """$ WAVEWATCH III Field Output
20260805 000000 3600 25
N
HS DIR SPR WND DTD FC CFX
3 4 2 1
0 1 2
T
ww3.
8
1 1000000 1 1000000
"""


def postprocess_region(region_id: str, gcs_base: str):
    print(f"=== Post-processing WW3 NetCDF for region '{region_id}' ===")
    work_dir = Path(f"/workspace/postproc_{region_id}")
    work_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(work_dir)

    # 1. Download binary files from GCS
    gcs_region_dir = f"{gcs_base}/{region_id}-output"
    print(f"Downloading mod_def.ww3 and out_grd.ww3 from {gcs_region_dir}...")
    subprocess.run(["gsutil", "cp", f"{gcs_region_dir}/mod_def.ww3", "."], check=True)
    subprocess.run(["gsutil", "cp", f"{gcs_region_dir}/out_grd.ww3", "."], check=True)

    # 2. Ensure ww3_ounf.nml is removed so ww3_ounf uses traditional ww3_ounf.inp
    if Path("ww3_ounf.nml").exists():
        Path("ww3_ounf.nml").unlink()

    # 3. Write the complete traditional ww3_ounf.inp schema.  The field
    # selector is followed by three additional control records and three file
    # layout records.  Omitting them lets ww3_ounf parse the selected fields
    # but then fail with ``PREMATURE END OF INPUT FILE``.
    #
    # The controls below request NetCDF-3 REAL variables, no swell partitions,
    # and all selected variables in one daily file.  The broad index range is
    # the documented way to select the entire regular grid.
    Path("ww3_ounf.inp").write_text(build_ounf_input())
    print("Created exact ww3_ounf.inp input file (N flag on Line 3).")

    # 4. Execute ww3_ounf
    print("Executing ww3_ounf binary...")
    res = subprocess.run(["ww3_ounf"], capture_output=True, text=True)
    print("ww3_ounf STDOUT:\n", res.stdout)
    if res.stderr:
        print("ww3_ounf STDERR:\n", res.stderr)
    if res.returncode:
        raise RuntimeError(
            f"ww3_ounf failed for region '{region_id}' with exit code "
            f"{res.returncode}"
        )

    # 5. Locate generated NetCDF file
    nc_files = list(Path(".").glob("ww3*.nc")) + list(Path(".").glob("*.nc"))
    if not nc_files:
        raise RuntimeError(f"ww3_ounf failed to produce NetCDF file for region '{region_id}'!")

    out_nc = nc_files[0]
    print(f"✅ Generated NetCDF file: {out_nc.name} ({out_nc.stat().st_size} bytes)")

    # 6. Verify NetCDF dataset with xarray
    ds = xr.open_dataset(out_nc)
    print("Dataset Variables:", list(ds.data_vars))
    print("Dataset Dimensions:", dict(ds.dims))
    ds.close()

    # 7. Upload to GCS as ww3_forecast.nc
    gcs_target = f"{gcs_region_dir}/ww3_forecast.nc"
    print(f"Uploading {out_nc} to {gcs_target}...")
    subprocess.run(["gsutil", "cp", str(out_nc), gcs_target], check=True)
    print(f"✅ Successfully post-processed and uploaded '{region_id}' wave forecast NetCDF!")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--gcs-base", default="gs://predsea-daily-outputs-test/predictions/2026-08-05/runs/ww3-24h-forecast")
    args = parser.parse_args()
    postprocess_region(args.region, args.gcs_base)

if __name__ == "__main__":
    main()
