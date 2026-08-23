from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


SWAN_HS_NAMES = ("hs", "VHM0", "significant_wave_height", "wave_height", "Swell_Height")
SWAN_TPP_NAMES = ("tpp", "TP_peak", "peak_wave_period", "wave_period", "peak_period", "tpp_peak")
SWAN_DIR_NAMES = ("dir", "VMDR", "mean_wave_direction", "wave_direction", "direction", "dir_mean")


class SwanInterpreterError(ValueError):
    """Raised when a SWAN NetCDF file cannot be interpreted."""


def get_swan_summary(
    lat: float,
    lon: float,
    time: str | None,
    swan_path: str | Path,
) -> dict[str, Any]:
    """Extract wave metrics for a point in a SWAN NetCDF file."""
    path = Path(swan_path)
    if not path.exists():
        raise SwanInterpreterError(f"SWAN NetCDF file not found: {path}")

    with xr.open_dataset(path) as dataset:
        time_index = _select_time_index(dataset, time)
        lat_name, lon_name = _lat_lon_names(dataset)
        grid = _nearest_grid_point(dataset, lat, lon, lat_name, lon_name)

        hs_name = _first_existing(dataset, SWAN_HS_NAMES)
        tpp_name = _first_existing(dataset, SWAN_TPP_NAMES, required=False)
        dir_name = _first_existing(dataset, SWAN_DIR_NAMES, required=False)

        hs = _point_value(dataset[hs_name], grid, time_index, lat_name, lon_name)
        tpp = _point_value(dataset[tpp_name], grid, time_index, lat_name, lon_name) if tpp_name else None
        wdir = _point_value(dataset[dir_name], grid, time_index, lat_name, lon_name) if dir_name else None

    # Wave direction in degrees (usually 0-360)
    cardinal = "N/A"
    if wdir is not None:
        from processing.mariner_interpreter import CARDINAL_DIRECTIONS
        # Convert meteorological angle to closest 45deg index
        index = int(((wdir + 22.5) % 360) / 45)
        cardinal = CARDINAL_DIRECTIONS[index]

    return {
        "model": "swan",
        "significant_wave_height_m": round(hs, 2),
        "peak_wave_period_s": round(tpp, 1) if tpp is not None else None,
        "wave_direction_degrees": round(wdir, 1) if wdir is not None else None,
        "wave_direction_cardinal": cardinal,
        "source": str(path),
        "location": {
            "requested": {"lat": float(lat), "lon": float(lon)},
            "nearest_grid": grid,
        },
    }


def nearest_grid_point_swan(swan_path: str | Path, lat: float, lon: float) -> dict[str, Any]:
    """Find nearest index coordinates on the SWAN grid."""
    with xr.open_dataset(swan_path) as dataset:
        lat_name, lon_name = _lat_lon_names(dataset)
        return _nearest_grid_point(dataset, lat, lon, lat_name, lon_name)


def get_swan_route_summary(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    time: str | None,
    swan_path: str | Path,
    samples: int = 8,
) -> dict[str, Any]:
    """Extract and summarize wave states along a route."""
    from processing.mariner_interpreter import sample_route_points

    route_points = sample_route_points(start_lat, start_lon, end_lat, end_lon, samples)
    sample_summaries = [
        get_swan_summary(lat=pt["lat"], lon=pt["lon"], time=time, swan_path=swan_path)
        for pt in route_points
    ]

    # Worst sampled point has maximum significant wave height
    worst = max(sample_summaries, key=lambda s: s["significant_wave_height_m"])

    return {
        "max_wave_height_m": worst["significant_wave_height_m"],
        "worst_point": worst,
        "samples": sample_summaries,
        "sample_count": len(sample_summaries),
        "source": str(swan_path),
    }


def _select_time_index(dataset: xr.Dataset, time: str | None) -> int:
    time_name = _time_name(dataset)
    if time_name is None:
        return 0
    if time is None or dataset.sizes.get(time_name, 1) == 1:
        return 0
    target = np.datetime64(time)
    values = dataset[time_name].values
    if np.issubdtype(values.dtype, np.datetime64):
        return int(np.abs(values - target).argmin())
    return 0


def _time_name(dataset: xr.Dataset) -> str | None:
    for name in ("time", "valid_time", "Time", "time_counter"):
        if name in dataset.coords or name in dataset.dims:
            return name
    return None


def _lat_lon_names(dataset: xr.Dataset) -> tuple[str, str]:
    lat_name = next((name for name in ("latitude", "lat", "XLAT", "nav_lat", "lat_nav") if name in dataset), None)
    lon_name = next((name for name in ("longitude", "lon", "XLONG", "nav_lon", "lon_nav") if name in dataset), None)
    if lat_name is None or lon_name is None:
        raise SwanInterpreterError("SWAN NetCDF is missing latitude/longitude coordinates.")
    return lat_name, lon_name


def _nearest_grid_point(
    dataset: xr.Dataset,
    lat: float,
    lon: float,
    lat_name: str,
    lon_name: str,
) -> dict[str, Any]:
    lats = dataset[lat_name]
    lons = dataset[lon_name]
    if lats.ndim == 1 and lons.ndim == 1:
        lat_index = int(np.abs(lats.values - lat).argmin())
        lon_index = int(np.abs(lons.values - lon).argmin())
        return {
            "lat": float(lats.values[lat_index]),
            "lon": float(lons.values[lon_index]),
            "lat_index": lat_index,
            "lon_index": lon_index,
        }

    distance = (lats - lat) ** 2 + ((lons - lon) * np.cos(np.deg2rad(lat))) ** 2
    grid_j, grid_i = np.unravel_index(int(np.argmin(distance.values)), distance.shape)
    return {
        "lat": float(lats.values[grid_j, grid_i]),
        "lon": float(lons.values[grid_j, grid_i]),
        "grid_i": int(grid_i),
        "grid_j": int(grid_j),
    }


def _point_value(
    variable: xr.DataArray,
    grid: dict[str, Any],
    time_index: int,
    lat_name: str,
    lon_name: str,
) -> float:
    selected = variable
    time_name = _time_name(variable.to_dataset(name="var"))
    if time_name and time_name in selected.dims:
        selected = selected.isel({time_name: time_index})

    if "lat_index" in grid and "lon_index" in grid:
        return float(selected.isel({lat_name: grid["lat_index"], lon_name: grid["lon_index"]}).values)
    return float(selected.values[grid["grid_j"], grid["grid_i"]])


def _first_existing(
    dataset: xr.Dataset,
    names: tuple[str, ...],
    required: bool = True,
) -> str | None:
    for name in names:
        if name in dataset:
            return name
    if required:
        raise SwanInterpreterError(f"SWAN NetCDF is missing one of: {', '.join(names)}")
    return None
