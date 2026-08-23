#!/usr/bin/env python3
"""
PredSea Standalone NetCDF Forecast Verification Script
Inspects variables, dimensions, coordinates, spatial resolution, and valid numerical ranges.

Usage:
  python scripts/verify_nc_forecast.py path/to/file.nc
"""

import sys
import argparse
from pathlib import Path
import xarray as xr
import numpy as np

def verify_netcdf(file_path: str):
    path = Path(file_path)
    if not path.exists():
        print(f"❌ Error: File '{file_path}' does not exist.")
        sys.exit(1)

    print(f"========================================================================")
    print(f"🔍 INSPECTING NETCDF FILE: {path.name}")
    print(f"File Size: {path.stat().st_size / (1024*1024):.2f} MB")
    print(f"========================================================================")

    ds = xr.open_dataset(path)

    # 1. Dimensions & Coordinates
    print("\n--- 1. DIMENSIONS & COORDINATES ---")
    for dim_name, dim_size in ds.sizes.items():
        print(f"  • Dimension '{dim_name}': {dim_size} points")

    for coord_name in ds.coords:
        coord = ds[coord_name]
        vals = np.atleast_1d(coord.values)
        if vals.size > 0:
            if np.issubdtype(vals.dtype, np.datetime64):
                print(f"  • Coordinate '{coord_name}': start={vals[0]}, end={vals[-1]}")
            else:
                try:
                    print(f"  • Coordinate '{coord_name}': range=[{vals.min():.4f}, {vals.max():.4f}], shape={coord.shape}")
                except Exception:
                    print(f"  • Coordinate '{coord_name}': shape={coord.shape}")

    # 2. Variables & Range Analysis
    print("\n--- 2. DATA VARIABLES ---")
    for var_name in ds.data_vars:
        v = ds[var_name]
        unit = v.attrs.get("units", "")
        long_name = v.attrs.get("long_name", var_name)
        print(f"  • Variable '{var_name}' ({long_name}):")
        print(f"      - Shape: {v.shape}, Dtype: {v.dtype}, Units: '{unit}'")

        if np.issubdtype(v.dtype, np.number):
            non_null = int(v.notnull().sum().values)
            null_count = int(v.isnull().sum().values)
            v_min = float(v.min().values) if non_null > 0 else float("nan")
            v_max = float(v.max().values) if non_null > 0 else float("nan")
            v_mean = float(v.mean().values) if non_null > 0 else float("nan")
            print(f"      - Range: min={v_min:.3f}, max={v_max:.3f}, mean={v_mean:.3f}")
            print(f"      - Cells: {non_null} valid data / {null_count} land mask NaNs")
        else:
            val_preview = str(v.values.flat[0]) if v.values.size > 0 else str(v.values)
            print(f"      - Non-numeric variable value: {val_preview}")

    # 3. Global Attributes
    print("\n--- 3. GLOBAL ATTRIBUTES ---")
    if ds.attrs:
        for k, v in ds.attrs.items():
            print(f"  • {k}: {v}")
    else:
        print("  (No global attributes present)")

    ds.close()
    print(f"\n========================================================================")
    print(f"✅ NetCDF Verification Completed Successfully for {path.name}")
    print(f"========================================================================")

def main():
    parser = argparse.ArgumentParser(description="Inspect NetCDF Wave Forecast File")
    parser.add_argument("file_path", help="Path to NetCDF file")
    args = parser.parse_args()
    verify_netcdf(args.file_path)

if __name__ == "__main__":
    main()
