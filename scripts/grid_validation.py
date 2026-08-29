import json
from pathlib import Path

import numpy as np
import xarray as xr

REGION_CONFIG_DIR = Path(__file__).resolve().parent.parent / "simulation" / "marine" / "regions"


def load_region(region_id: str) -> dict:
    region_path = REGION_CONFIG_DIR / f"{region_id}.json"
    if not region_path.exists():
        region_path = Path("config/marine_regions") / f"{region_id}.json"
    with open(region_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_region_bbox(region_id: str) -> dict:
    return load_region(region_id)["bbox"]


def validate_grid_matches_region(grid_path: str, region_id: str, tol: float = 0.05) -> None:
    if tol < 0:
        raise ValueError("Grid geographic tolerance must be non-negative")

    region = load_region(region_id)
    bbox = region["bbox"]
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

        compiled_shape = (
            region.get("models", {}).get("croco", {}).get("compiled_grid_shape")
        )
        if compiled_shape is not None:
            expected_shape = (
                int(compiled_shape["eta_rho"]),
                int(compiled_shape["xi_rho"]),
            )
            if lon.shape != expected_shape or lat.shape != expected_shape:
                raise ValueError(
                    f"Grid dimensions for {region_id} do not match compiled CROCO "
                    f"shape: expected eta_rho/xi_rho={expected_shape}, "
                    f"actual lon={lon.shape}, lat={lat.shape}"
                )

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
