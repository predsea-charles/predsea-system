#!/usr/bin/env python3
"""
Validate assets/static_grids/med_basin_1km_bathymetry_swan.nc before it goes
into the croco-batch image rebuild.

Checks the exact things scripts/prepare_swan_run.py's prepare() function will
assume are true when it opens this file at runtime (see the code comments
below for the specific line each check maps to):

  - Opens as a NetCDF with `depth`, `longitude`, `latitude` (prepare_swan_run.py
    does `xr.open_dataset(bathymetry_path)` then reads `depth`/`longitude`/`latitude`
    directly by name -- no fallback names are tried).
  - longitude/latitude are strictly increasing (prepare_swan_run.py raises
    ValueError "bathymetry coordinates must increase west-east and south-north"
    otherwise).
  - Coverage fully contains med_basin_1km.json's bbox (lon -6..14, lat 35..44.5)
    -- prepare_swan_run.py does `.sel(longitude=slice(lon_min, lon_max), ...)`,
    which silently returns a smaller/empty slice rather than erroring if the
    file doesn't actually cover the requested bbox.
  - depth values are sane: not all-NaN, not all-zero, and mostly non-negative
    (prepare_swan_run.py itself does `bottom[bottom <= 0.0] = -999.0`, treating
    <=0 as land/exception value -- so a real ocean bathymetry file should have
    a mix of positive depths and some <=0 values for land, not one extreme).

Run from the repo root with the same venv that has xarray/numpy already
installed (the one used for prepare_bathymetry.py and the rest of this
pipeline):

    python3 validate_basin_bathymetry.py
    # or, to point at a different file:
    python3 validate_basin_bathymetry.py --path assets/static_grids/med_basin_1km_bathymetry_swan.nc
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        default="assets/static_grids/med_basin_1km_bathymetry_swan.nc",
        help="Path to the bathymetry NetCDF to validate.",
    )
    parser.add_argument(
        "--region-profile",
        default="simulation/marine/regions/med_basin_1km.json",
        help="Region profile whose bbox this bathymetry file must fully cover.",
    )
    args = parser.parse_args()

    path = Path(args.path)
    errors: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        print(f"❌ File does not exist: {path}")
        return 1

    print(f"Opening {path} ({path.stat().st_size / 1_048_576:.1f} MiB)...")
    try:
        ds = xr.open_dataset(path)
    except Exception as exc:
        print(f"❌ Failed to open as NetCDF: {exc}")
        return 1

    print(f"Variables: {list(ds.data_vars)}")
    print(f"Coordinates: {list(ds.coords)}")

    # --- required variables/coords, exact names (no fallback in prepare_swan_run.py) ---
    for required in ("depth",):
        if required not in ds.variables:
            errors.append(f"missing required variable '{required}' (prepare_swan_run.py reads it by this exact name)")
    for required in ("longitude", "latitude"):
        if required not in ds.coords and required not in ds.variables:
            errors.append(f"missing required coordinate '{required}'")

    if errors:
        print("\n".join(f"❌ {e}" for e in errors))
        return 1

    lon = np.asarray(ds["longitude"].values)
    lat = np.asarray(ds["latitude"].values)
    depth = np.asarray(ds["depth"].values)

    print(f"\nlongitude: {lon.size} points, range [{lon.min():.4f}, {lon.max():.4f}]")
    print(f"latitude:  {lat.size} points, range [{lat.min():.4f}, {lat.max():.4f}]")
    print(f"depth shape: {depth.shape}, dtype: {depth.dtype}")

    # --- monotonicity (prepare_swan_run.py's own hard requirement) ---
    if not np.all(np.diff(lon) > 0):
        errors.append("longitude is not strictly increasing west->east")
    if not np.all(np.diff(lat) > 0):
        errors.append("latitude is not strictly increasing south->north")

    # --- coverage vs. the region profile's bbox ---
    region_path = Path(args.region_profile)
    if region_path.exists():
        region = json.loads(region_path.read_text())
        bbox = region["bbox"]
        print(f"\nRegion profile bbox ({region_path.name}): "
              f"lon [{bbox['longitude_min']}, {bbox['longitude_max']}], "
              f"lat [{bbox['latitude_min']}, {bbox['latitude_max']}]")
        if lon.min() > bbox["longitude_min"] or lon.max() < bbox["longitude_max"]:
            errors.append(
                f"longitude coverage [{lon.min():.4f}, {lon.max():.4f}] does not fully "
                f"contain the region bbox [{bbox['longitude_min']}, {bbox['longitude_max']}]"
            )
        if lat.min() > bbox["latitude_min"] or lat.max() < bbox["latitude_max"]:
            errors.append(
                f"latitude coverage [{lat.min():.4f}, {lat.max():.4f}] does not fully "
                f"contain the region bbox [{bbox['latitude_min']}, {bbox['latitude_max']}]"
            )
    else:
        warnings.append(f"region profile not found at {region_path}, skipped coverage check")

    # --- depth sanity ---
    finite = np.isfinite(depth)
    finite_frac = finite.mean()
    print(f"\ndepth: {finite_frac:.1%} finite, min={np.nanmin(depth):.1f}, "
          f"max={np.nanmax(depth):.1f}, mean={np.nanmean(depth):.1f}")
    if finite_frac < 0.5:
        errors.append(f"depth is mostly non-finite ({finite_frac:.1%} finite) -- looks broken")
    positive_frac = (depth[finite] > 0).mean() if finite.any() else 0.0
    print(f"depth: {positive_frac:.1%} of finite values are > 0 (ocean)")
    if positive_frac < 0.05:
        errors.append(f"almost no positive depth values ({positive_frac:.1%}) -- looks like it's all land/zero, not real ocean bathymetry")
    if positive_frac > 0.999:
        warnings.append(f"{positive_frac:.1%} of values are positive -- no land at all is unusual for a Mediterranean-wide bbox, worth a visual sanity check")

    print()
    for w in warnings:
        print(f"⚠️  {w}")
    if errors:
        for e in errors:
            print(f"❌ {e}")
        print(f"\n{len(errors)} problem(s) found.")
        return 1

    print("✅ All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
