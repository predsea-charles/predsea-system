import json
from pathlib import Path

import numpy as np
import xarray as xr

REGION_CONFIG_DIR = Path(__file__).resolve().parent.parent / "simulation" / "marine" / "regions"


def load_region_bbox(region_id: str) -> dict:
    region_path = REGION_CONFIG_DIR / f"{region_id}.json"
    if not region_path.exists():
        region_path = Path("config/marine_regions") / f"{region_id}.json"
    with open(region_path, "r", encoding="utf-8") as f:
        return json.load(f)["bbox"]


def validate_grid_matches_region(grid_path: str, region_id: str, tol: float = 0.05) -> None:
    if tol < 0:
        raise ValueError("Grid geographic tolerance must be non-negative")

    bbox = load_region_bbox(region_id)
    with xr.open_dataset(grid_path) as ds:
        missing = {"lon_rho", "lat_rho"} - set(ds.variables)
        if missing:
            raise ValueError(
                f"Grid for {region_id} is missing geographic variables: "
                f"{', '.join(sorted(missing))}"
            )

        grid_region_attr = ds.attrs.get("region_id")
        if grid_region_attr is not None and grid_region_attr != region_id:
            raise ValueError(
                f"Grid region_id mismatch for {region_id}: "
                f"file declares region_id={grid_region_attr!r}"
            )

        lon = np.asarray(ds["lon_rho"].values, dtype=float)
        lat = np.asarray(ds["lat_rho"].values, dtype=float)
        if lon.size == 0 or lat.size == 0 or not np.isfinite(lon).all() or not np.isfinite(lat).all():
            raise ValueError(f"Grid coordinates for {region_id} must be non-empty and finite")

        lon_min, lon_max = float(lon.min()), float(lon.max())
        lat_min, lat_max = float(lat.min()), float(lat.max())

    actual = {
        "longitude_min": lon_min,
        "longitude_max": lon_max,
        "latitude_min": lat_min,
        "latitude_max": lat_max,
    }
    mismatches = {
        edge: {"expected": float(bbox[edge]), "actual": value}
        for edge, value in actual.items()
        if abs(value - float(bbox[edge])) > tol
    }
    if mismatches:
        raise ValueError(
            f"Grid coordinates for {region_id} do not match expected bbox "
            f"within {tol} degrees.\n"
            f"  Expected bbox: {bbox}\n"
            f"  Actual bbox: {actual}\n"
            f"  Mismatched edges: {mismatches}"
        )
