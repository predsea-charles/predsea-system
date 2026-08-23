#!/usr/bin/env python3
"""
Ground-truth check: compare each region's generated land/water mask
(depth<=0 = land, from assets/static_grids/*_bathymetry_swan.nc) against
an independent, authoritative coastline dataset (GSHHG, via the
`global_land_mask` package), rather than inferring problems only from
internal self-consistency checks (which, per analyze_bathymetry_masks.py,
turned out inconclusive -- isolated-cell counts didn't distinguish broken
from working regions).

This answers directly: for each region, what fraction of cells does our
EMODnet-derived bathymetry classify differently from a real coastline
reference? A high "false land" rate (we say land, GSHHG says water) or
"false water" rate (we say water, GSHHG says land) -- especially
concentrated in specific sub-areas rather than spread thinly along every
coastline -- is direct, ground-truthed evidence of a data/processing
defect, not just an artifact of two different coastline resolutions
disagreeing by a pixel here and there near real coastlines (which is
normal and expected at boundaries).

Requires the `global_land_mask` package (bundles a ~1 arc-minute GSHHG
derived grid, no network access needed at runtime beyond the one-time
pip install):

    pip install global-land-mask

Run:
    .venv311/bin/python3 analyze_bathymetry_vs_coastline.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr

try:
    from global_land_mask import globe
except ImportError:
    print("Missing dependency. Install it with:\n\n    .venv311/bin/pip install global-land-mask\n")
    raise SystemExit(1)

REPO_ROOT = Path(__file__).resolve().parent
REGIONS_DIR = REPO_ROOT / "simulation" / "marine" / "regions"
BATHY_DIR = REPO_ROOT / "assets" / "static_grids"

REGIONS = [
    ("alboran_1km", "BROKEN"),
    ("gulf_of_lion_1km", "BROKEN"),
    ("algerian_1km", "BROKEN"),
    ("balearic_1km", "working"),
    ("tyrrhenian_1km", "working"),
]


def main() -> None:
    print(f"{'region':18} {'status':8} {'grid':14} {'our %land':10} {'gshhg %land':12} {'false_land%':12} {'false_water%':13} {'mismatch%'}")
    for region_id, status in REGIONS:
        path = BATHY_DIR / f"{region_id}_bathymetry_swan.nc"
        if not path.exists():
            print(f"{region_id:18} FILE NOT FOUND: {path}")
            continue

        ds = xr.open_dataset(path)
        depth = np.asarray(ds["depth"].values, dtype=np.float64)
        lon = np.asarray(ds["longitude"].values, dtype=np.float64)
        lat = np.asarray(ds["latitude"].values, dtype=np.float64)
        ds.close()

        our_land = depth <= 0.0

        lon_mesh, lat_mesh = np.meshgrid(lon, lat)
        # global_land_mask expects longitudes in [-180, 180], which all our
        # regions already are.
        gshhg_land = globe.is_land(lat_mesh, lon_mesh)

        our_pct_land = our_land.mean() * 100
        gshhg_pct_land = gshhg_land.mean() * 100

        false_land = our_land & (~gshhg_land)     # we say land, truth says water
        false_water = (~our_land) & gshhg_land    # we say water, truth says land
        false_land_pct = false_land.mean() * 100
        false_water_pct = false_water.mean() * 100
        mismatch_pct = (our_land != gshhg_land).mean() * 100

        print(
            f"{region_id:18} {status:8} {depth.shape!s:14} "
            f"{our_pct_land:8.1f}%  {gshhg_pct_land:9.1f}%   "
            f"{false_land_pct:9.1f}%   {false_water_pct:10.1f}%   {mismatch_pct:7.1f}%"
        )

        # Flag concentrated blocks of false_land / false_water (a contiguous
        # patch, not scattered coastline-boundary noise) as the strongest
        # signal of a real data defect vs. two datasets disagreeing on
        # exactly where the coastline pixel boundary falls.
        for label, mask in (("false_land", false_land), ("false_water", false_water)):
            if mask.sum() == 0:
                continue
            ys, xs = np.where(mask)
            # crude "concentration" signal: does >30% of all mismatches of
            # this type fall within a single 20x20-cell box?
            from collections import Counter
            block_counts = Counter(zip(ys // 20, xs // 20))
            top_block, top_count = block_counts.most_common(1)[0]
            if top_count / mask.sum() > 0.3 and mask.sum() > 50:
                by, bx = top_block
                lat_range = (lat[by * 20], lat[min((by + 1) * 20, len(lat) - 1)])
                lon_range = (lon[bx * 20], lon[min((bx + 1) * 20, len(lon) - 1)])
                print(
                    f"    -> {label}: {top_count}/{mask.sum()} mismatches concentrated in one block "
                    f"around lat {lat_range}, lon {lon_range} -- worth a visual check"
                )

    print()
    print("Read false_land_pct / false_water_pct as the headline numbers. A few")
    print("percent scattered along real coastlines is normal (resolution/dataset")
    print("disagreement). Numbers well above that, especially concentrated in one")
    print("block per the notes above, point at a genuine defect in this region's")
    print("bathymetry generation -- worth then diffing against the raw EMODnet TIFF")
    print("(simulation/inputs/emodnet_bathymetry_raw.tiff, if still present, or a")
    print("fresh --dry-run False download) to see exactly where the sign/interpolation")
    print("logic in scripts/prepare_bathymetry.py went wrong.")


if __name__ == "__main__":
    main()
