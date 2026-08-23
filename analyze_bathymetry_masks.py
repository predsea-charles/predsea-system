#!/usr/bin/env python3
"""
Diagnose the alboran/gulf_of_lion/algerian SWAN bathymetry land/water
misclassification bug directly from the generated .nc files in
assets/static_grids/, without needing a real coastline reference dataset
for a first pass.

Two things this checks, both testable from the file alone:

1. Isolated-cell defects: single land cells fully surrounded by water, or
   single wet cells fully surrounded by land. These are exactly what
   SWAN's own PRINT-*** files flagged as "isolated wet point" / "1D
   configuration" warnings during the basin-wide test on 2026-08-03 --
   i.e. this independently reproduces that same class of defect on the
   per-region files, without needing to run SWAN at all.

2. A specific bug candidate in scripts/prepare_bathymetry.py: the land/
   ocean sign convention is decided ONCE per region from the mean of the
   whole raw EMODnet elevation grid (`is_depth_positive = np.nanmean(...)
   > 0`), not from a fixed physical convention. EMODnet's convention is
   always "negative = below sea level", so this should be a constant
   rule, not an inference -- for a region whose bbox happens to contain a
   lot of land relative to sea (alboran/gulf_of_lion/algerian's bboxes
   all include long stretches of coastline relative to their small area,
   vs. balearic/tyrrhenian which are more open-sea-dominated), this
   per-region inference could pick the wrong sign for the whole grid, or
   sit close enough to zero that noise flips individual cells.

This can't fully prove root cause (the pre-flip raw EMODnet array isn't
saved anywhere), but the isolated-cell counts and land-fraction numbers
below should make it obvious whether alboran/gulf_of_lion/algerian look
qualitatively different from balearic/tyrrhenian, and roughly how bad it is.

Run from the repo root with a venv that has xarray/numpy (.venv311 or
.venv both have it):

    .venv311/bin/python3 analyze_bathymetry_masks.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr

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


def count_isolated_cells(is_land: np.ndarray) -> tuple[int, int]:
    """Count single-cell islands of land-in-water and wet-point-in-land,
    using a strict 4-neighbor (N/S/E/W) majority test -- a cell is
    "isolated" if ALL 4 of its in-bounds neighbors have the opposite
    classification. Matches the kind of defect SWAN itself flagged
    ("isolated wet point", "1D configuration") in the basin-wide test.
    """
    ny, nx = is_land.shape
    isolated_land = 0
    isolated_wet = 0
    # Vectorized: pad with the cell's own value at borders so edges don't
    # spuriously count as isolated just because they have fewer neighbors.
    padded = np.pad(is_land, 1, mode="edge")
    north = padded[0:-2, 1:-1]
    south = padded[2:, 1:-1]
    east = padded[1:-1, 2:]
    west = padded[1:-1, 0:-2]

    all_opposite_of_land = (~north.astype(bool)) & (~south.astype(bool)) & (~east.astype(bool)) & (~west.astype(bool))
    all_opposite_of_wet = north.astype(bool) & south.astype(bool) & east.astype(bool) & west.astype(bool)

    isolated_land = int(np.sum(is_land & all_opposite_of_land))
    isolated_wet = int(np.sum((~is_land) & all_opposite_of_wet))
    return isolated_land, isolated_wet


def main() -> None:
    print(f"{'region':18} {'status':8} {'bbox (lon x lat, deg)':24} {'aspect':7} {'area_deg2':10} {'tiled?':7}")
    region_info = {}
    for region_id, status in REGIONS:
        profile_path = REGIONS_DIR / f"{region_id}.json"
        profile = json.loads(profile_path.read_text())
        bbox = profile["bbox"]
        w = bbox["longitude_max"] - bbox["longitude_min"]
        h = bbox["latitude_max"] - bbox["latitude_min"]
        area = w * h
        aspect = max(w, h) / min(w, h)
        tiled = "yes" if area > 16.0 else "no"
        region_info[region_id] = dict(w=w, h=h, area=area, aspect=aspect, tiled=tiled)
        print(f"{region_id:18} {status:8} {w:.2f} x {h:.2f}{'':10} {aspect:.2f}:1  {area:8.2f}   {tiled}")

    print()
    print(f"{'region':18} {'status':8} {'grid':12} {'%land':7} {'%ocean':7} {'depth min/max/mean':22} {'isolated_land':13} {'isolated_wet'}")
    for region_id, status in REGIONS:
        # Older files may lack the _1km suffix (balearic's known historical
        # quirk) -- try the exact name first, then fall back.
        candidates = [
            BATHY_DIR / f"{region_id}_bathymetry_swan.nc",
        ]
        path = next((c for c in candidates if c.exists()), None)
        if path is None:
            print(f"{region_id:18} {status:8} FILE NOT FOUND in {BATHY_DIR}")
            continue

        ds = xr.open_dataset(path)
        depth = np.asarray(ds["depth"].values, dtype=np.float64)
        is_land = depth <= 0.0
        pct_land = is_land.mean() * 100
        pct_ocean = 100 - pct_land
        isolated_land, isolated_wet = count_isolated_cells(is_land)

        print(
            f"{region_id:18} {status:8} {depth.shape!s:12} "
            f"{pct_land:5.1f}% {pct_ocean:5.1f}%  "
            f"{np.nanmin(depth):7.1f}/{np.nanmax(depth):7.1f}/{np.nanmean(depth):7.1f}   "
            f"{isolated_land:13} {isolated_wet}"
        )
        ds.close()

    print()
    print("Interpretation:")
    print("- isolated_land = single land cells (depth<=0) with all 4 neighbors wet.")
    print("  Each one is a spurious 'obstacle' SWAN's decomposition has to route around.")
    print("- isolated_wet  = single wet cells with all 4 neighbors land.")
    print("  Each one is exactly the 'isolated wet point' defect SWAN's own PRINT logs")
    print("  flagged during the 2026-08-03 basin-wide test.")
    print("- If alboran/gulf_of_lion/algerian show meaningfully higher isolated-cell")
    print("  counts (esp. relative to their grid size) than balearic/tyrrhenian, that's")
    print("  direct, reproducible evidence the bathymetry data itself is the problem,")
    print("  independent of domain shape/aspect ratio.")


if __name__ == "__main__":
    main()
