#!/usr/bin/env python3
"""Create a CROCO C-grid from a versioned PredSea bathymetry product."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import xarray as xr

try:
    from scripts.validate_marine_region import validate_region
    from scripts.grid_validation import validate_grid_matches_region
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from validate_marine_region import validate_region
    from grid_validation import validate_grid_matches_region


EARTH_RADIUS_M = 6_371_000.0
EARTH_ROTATION_S = 7.2921159e-5
CROCO_REQUIRED_GRID_VARIABLES = frozenset(
    {
        "spherical",
        "xl",
        "el",
        "h",
        "f",
        "pm",
        "pn",
        "lon_rho",
        "lat_rho",
        "lon_u",
        "lat_u",
        "lon_v",
        "lat_v",
        "angle",
        "mask_rho",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _distance_m(
    lon_a: np.ndarray,
    lat_a: np.ndarray,
    lon_b: np.ndarray,
    lat_b: np.ndarray,
) -> np.ndarray:
    mean_lat = np.deg2rad((lat_a + lat_b) * 0.5)
    dx = np.deg2rad(lon_b - lon_a) * np.cos(mean_lat)
    dy = np.deg2rad(lat_b - lat_a)
    return EARTH_RADIUS_M * np.hypot(dx, dy)


def _maximum_rx0(depth: np.ndarray, wet: np.ndarray) -> float:
    maxima = [0.0]
    for axis in (0, 1):
        first = np.take(depth, range(depth.shape[axis] - 1), axis=axis)
        second = np.take(depth, range(1, depth.shape[axis]), axis=axis)
        wet_first = np.take(wet, range(wet.shape[axis] - 1), axis=axis)
        wet_second = np.take(wet, range(1, wet.shape[axis]), axis=axis)
        pair_wet = wet_first & wet_second
        denominator = first + second
        ratio = np.zeros_like(first, dtype=float)
        valid = pair_wet & (denominator > 0)
        ratio[valid] = np.abs(second[valid] - first[valid]) / denominator[valid]
        if valid.any():
            maxima.append(float(ratio[valid].max()))
    return max(maxima)


def crop_bathymetry_to_bbox(
    bathymetry: xr.Dataset,
    bbox: dict[str, float],
) -> xr.Dataset:
    """Subset a rectilinear/near-rectilinear source grid to a region bbox."""
    for name in ("bathy", "nav_lon", "nav_lat"):
        if name not in bathymetry:
            raise ValueError(f"bathymetry is missing {name}")
    depth = bathymetry["bathy"]
    if depth.ndim != 2:
        raise ValueError("bathymetry must be a two-dimensional grid")
    dims = depth.dims
    lon = np.asarray(bathymetry["nav_lon"].values, dtype=float)
    lat = np.asarray(bathymetry["nav_lat"].values, dtype=float)
    inside = (
        (lon >= bbox["longitude_min"])
        & (lon <= bbox["longitude_max"])
        & (lat >= bbox["latitude_min"])
        & (lat <= bbox["latitude_max"])
    )
    row_indices = np.flatnonzero(inside.any(axis=1))
    column_indices = np.flatnonzero(inside.any(axis=0))
    if row_indices.size < 3 or column_indices.size < 3:
        raise ValueError("source bathymetry does not cover the requested region bbox")
    cropped = bathymetry.isel(
        {
            dims[0]: slice(int(row_indices[0]), int(row_indices[-1]) + 1),
            dims[1]: slice(int(column_indices[0]), int(column_indices[-1]) + 1),
        }
    )
    cropped_lon = np.asarray(cropped["nav_lon"].values, dtype=float)
    cropped_lat = np.asarray(cropped["nav_lat"].values, dtype=float)
    actual = {
        "longitude_min": float(cropped_lon.min()),
        "longitude_max": float(cropped_lon.max()),
        "latitude_min": float(cropped_lat.min()),
        "latitude_max": float(cropped_lat.max()),
    }
    longitude_step = float(np.nanmedian(np.abs(np.diff(lon, axis=1))))
    latitude_step = float(np.nanmedian(np.abs(np.diff(lat, axis=0))))
    tolerances = {
        "longitude_min": longitude_step * 1.01,
        "longitude_max": longitude_step * 1.01,
        "latitude_min": latitude_step * 1.01,
        "latitude_max": latitude_step * 1.01,
    }
    mismatches = [
        key
        for key, expected in bbox.items()
        if abs(actual[key] - float(expected)) > tolerances[key]
    ]
    if mismatches:
        raise ValueError(
            "cropped bathymetry does not match requested bbox for: "
            + ", ".join(sorted(mismatches))
        )
    return cropped


def smooth_bathymetry(
    depth: np.ndarray,
    wet: np.ndarray,
    *,
    maximum_rx0: float,
    maximum_iterations: int = 10_000,
) -> tuple[np.ndarray, int, float]:
    """Deepen shallow cells until every wet-neighbour pair satisfies rx0."""
    smoothed = np.asarray(depth, dtype=float).copy()
    factor = (1.0 + maximum_rx0) / (1.0 - maximum_rx0)
    for iteration in range(maximum_iterations + 1):
        current = _maximum_rx0(smoothed, wet)
        if current <= maximum_rx0 + 1e-12:
            return smoothed, iteration, current
        changed = False
        for axis in (0, 1):
            left_slice = [slice(None), slice(None)]
            right_slice = [slice(None), slice(None)]
            left_slice[axis] = slice(0, -1)
            right_slice[axis] = slice(1, None)
            left_slice = tuple(left_slice)
            right_slice = tuple(right_slice)
            left = smoothed[left_slice]
            right = smoothed[right_slice]
            pair_wet = wet[left_slice] & wet[right_slice]

            required_right = left / factor
            update_right = pair_wet & (right < required_right)
            if update_right.any():
                right[update_right] = required_right[update_right]
                changed = True

            required_left = right / factor
            update_left = pair_wet & (left < required_left)
            if update_left.any():
                left[update_left] = required_left[update_left]
                changed = True
        if not changed:
            break
    raise ValueError(
        f"bathymetry smoothing did not reach rx0 <= {maximum_rx0} "
        f"after {maximum_iterations} iterations"
    )


def build_grid(
    bathymetry: xr.Dataset,
    *,
    minimum_depth_m: float = 10.0,
    maximum_rx0: float = 0.15,
) -> tuple[xr.Dataset, dict]:
    for name in ("bathy", "nav_lon", "nav_lat"):
        if name not in bathymetry:
            raise ValueError(f"bathymetry is missing {name}")
    raw_depth = np.asarray(bathymetry["bathy"].values, dtype=float)
    lon_rho = np.asarray(bathymetry["nav_lon"].values, dtype=float)
    lat_rho = np.asarray(bathymetry["nav_lat"].values, dtype=float)
    if raw_depth.shape != lon_rho.shape or raw_depth.shape != lat_rho.shape:
        raise ValueError("bathymetry and navigation coordinates have different shapes")
    if raw_depth.ndim != 2 or min(raw_depth.shape) < 3:
        raise ValueError("bathymetry must be a two-dimensional grid")

    mask_rho = np.isfinite(raw_depth) & (raw_depth >= minimum_depth_m)
    if not mask_rho.any():
        raise ValueError("bathymetry contains no wet cells")
    initial = np.where(mask_rho, np.maximum(raw_depth, minimum_depth_m), minimum_depth_m)
    smoothed, smoothing_iterations, achieved_rx0 = smooth_bathymetry(
        initial,
        mask_rho,
        maximum_rx0=maximum_rx0,
    )
    h = np.where(mask_rho, smoothed, minimum_depth_m)
    depth_change = h[mask_rho] - raw_depth[mask_rho]

    lon_u = 0.5 * (lon_rho[:, :-1] + lon_rho[:, 1:])
    lat_u = 0.5 * (lat_rho[:, :-1] + lat_rho[:, 1:])
    lon_v = 0.5 * (lon_rho[:-1, :] + lon_rho[1:, :])
    lat_v = 0.5 * (lat_rho[:-1, :] + lat_rho[1:, :])
    lon_psi = 0.25 * (
        lon_rho[:-1, :-1]
        + lon_rho[1:, :-1]
        + lon_rho[:-1, 1:]
        + lon_rho[1:, 1:]
    )
    lat_psi = 0.25 * (
        lat_rho[:-1, :-1]
        + lat_rho[1:, :-1]
        + lat_rho[:-1, 1:]
        + lat_rho[1:, 1:]
    )

    dx_edges = _distance_m(
        lon_rho[:, :-1], lat_rho[:, :-1], lon_rho[:, 1:], lat_rho[:, 1:]
    )
    dy_edges = _distance_m(
        lon_rho[:-1, :], lat_rho[:-1, :], lon_rho[1:, :], lat_rho[1:, :]
    )
    dx = np.empty_like(lon_rho)
    dy = np.empty_like(lat_rho)
    dx[:, 1:-1] = 0.5 * (dx_edges[:, :-1] + dx_edges[:, 1:])
    dx[:, 0] = dx_edges[:, 0]
    dx[:, -1] = dx_edges[:, -1]
    dy[1:-1, :] = 0.5 * (dy_edges[:-1, :] + dy_edges[1:, :])
    dy[0, :] = dy_edges[0, :]
    dy[-1, :] = dy_edges[-1, :]

    # CROCO reads these scalar basin lengths before any gridded arrays.  Use
    # the median full-row/full-column geodesic length so mildly curvilinear
    # spherical grids retain a representative physical XI/ETA extent.
    xl = float(np.median(dx.sum(axis=1)))
    el = float(np.median(dy.sum(axis=0)))

    mask_u = mask_rho[:, :-1] & mask_rho[:, 1:]
    mask_v = mask_rho[:-1, :] & mask_rho[1:, :]
    mask_psi = (
        mask_rho[:-1, :-1]
        & mask_rho[1:, :-1]
        & mask_rho[:-1, 1:]
        & mask_rho[1:, 1:]
    )

    grid = xr.Dataset(
        data_vars={
            "lon_rho": (("eta_rho", "xi_rho"), lon_rho),
            "lat_rho": (("eta_rho", "xi_rho"), lat_rho),
            "lon_u": (("eta_u", "xi_u"), lon_u),
            "lat_u": (("eta_u", "xi_u"), lat_u),
            "lon_v": (("eta_v", "xi_v"), lon_v),
            "lat_v": (("eta_v", "xi_v"), lat_v),
            "lon_psi": (("eta_psi", "xi_psi"), lon_psi),
            "lat_psi": (("eta_psi", "xi_psi"), lat_psi),
            "h": (("eta_rho", "xi_rho"), h),
            "hraw": (("bath", "eta_rho", "xi_rho"), raw_depth[np.newaxis, ...]),
            "mask_rho": (("eta_rho", "xi_rho"), mask_rho.astype(np.int8)),
            "mask_u": (("eta_u", "xi_u"), mask_u.astype(np.int8)),
            "mask_v": (("eta_v", "xi_v"), mask_v.astype(np.int8)),
            "mask_psi": (("eta_psi", "xi_psi"), mask_psi.astype(np.int8)),
            "pm": (("eta_rho", "xi_rho"), 1.0 / dx),
            "pn": (("eta_rho", "xi_rho"), 1.0 / dy),
            "angle": (("eta_rho", "xi_rho"), np.zeros_like(lon_rho)),
            "f": (
                ("eta_rho", "xi_rho"),
                2.0 * EARTH_ROTATION_S * np.sin(np.deg2rad(lat_rho)),
            ),
            "spherical": ((), np.bytes_("T")),
            "xl": ((), xl),
            "el": ((), el),
        },
        attrs={
            "title": "PredSea CROCO regional grid",
            "schema_version": "predsea.croco_grid.v1",
            "minimum_depth_m": minimum_depth_m,
            "maximum_rx0": maximum_rx0,
            "achieved_rx0": achieved_rx0,
            "smoothing_iterations": smoothing_iterations,
        },
    )
    report = {
        "schema_version": "predsea.croco_grid_validation.v1",
        "status": "succeeded",
        "shape": list(raw_depth.shape),
        "wet_cell_count": int(mask_rho.sum()),
        "wet_fraction": float(mask_rho.mean()),
        "minimum_wet_depth_m": float(h[mask_rho].min()),
        "maximum_wet_depth_m": float(h[mask_rho].max()),
        "changed_wet_cell_fraction": float((depth_change > 1e-6).mean()),
        "mean_wet_cell_deepening_m": float(depth_change.mean()),
        "p95_wet_cell_deepening_m": float(np.percentile(depth_change, 95)),
        "maximum_wet_cell_deepening_m": float(depth_change.max()),
        "maximum_rx0": achieved_rx0,
        "smoothing_iterations": smoothing_iterations,
        "dx_m": [float(dx.min()), float(dx.max())],
        "dy_m": [float(dy.min()), float(dy.max())],
        "xl_m": xl,
        "el_m": el,
        "bbox": [
            float(lon_rho.min()),
            float(lat_rho.min()),
            float(lon_rho.max()),
            float(lat_rho.max()),
        ],
    }
    missing = CROCO_REQUIRED_GRID_VARIABLES.difference(grid.variables)
    if missing:
        raise ValueError(
            "generated grid is missing CROCO-required variables: "
            + ", ".join(sorted(missing))
        )
    return grid, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", type=Path, required=True)
    parser.add_argument("--bathymetry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--minimum-depth-m", type=float, default=10.0)
    parser.add_argument("--maximum-rx0", type=float, default=0.18)
    args = parser.parse_args(argv)

    region_validation = validate_region(args.region)
    if region_validation["status"] != "succeeded":
        raise SystemExit(
            "Marine region profile failed preflight: "
            + "; ".join(region_validation["errors"])
        )
    region = json.loads(args.region.read_text())
    with xr.open_dataset(args.bathymetry) as source_bathymetry:
        bathymetry = crop_bathymetry_to_bbox(source_bathymetry, region["bbox"])
        grid, report = build_grid(
            bathymetry,
            minimum_depth_m=args.minimum_depth_m,
            maximum_rx0=args.maximum_rx0,
        )
        grid.attrs.update(
            region_id=region["region_id"],
            region_profile_sha256=_sha256(args.region),
            source_bathymetry_sha256=_sha256(args.bathymetry),
            created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        grid.to_netcdf(args.output)
    validate_grid_matches_region(str(args.output), region["region_id"])
    report.update(
        region_id=region["region_id"],
        requested_bbox=region["bbox"],
        output=str(args.output),
        output_size_bytes=args.output.stat().st_size,
        output_sha256=_sha256(args.output),
        source_bathymetry=str(args.bathymetry),
        source_bathymetry_sha256=_sha256(args.bathymetry),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
