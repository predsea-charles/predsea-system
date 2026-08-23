from __future__ import annotations

from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from processing.mariner_interpreter import MPS_TO_KNOTS, wind_direction_cardinal


NEMO_UO_NAMES = ("uo", "u_current", "u", "eastward_sea_water_velocity")
NEMO_VO_NAMES = ("vo", "v_current", "v", "northward_sea_water_velocity")
NEMO_SSH_NAMES = ("zos", "ssh", "sea_surface_height", "sea_surface_height_above_geoid")
NEMO_SST_NAMES = ("tos", "sst", "temperature_surface", "sea_surface_temperature", "tos_surface")
NEMO_SALINITY_NAMES = ("sos", "salinity", "sea_surface_salinity", "so")


class NemoInterpreterError(ValueError):
    """Raised when a NEMO NetCDF file cannot be interpreted."""


def get_nemo_summary(
    lat: float,
    lon: float,
    time: str | None,
    nemo_path: str | Path,
) -> dict[str, Any]:
    """Extract surface oceanographic metrics for a point in a NEMO NetCDF file."""
    path = Path(nemo_path)
    if not path.exists():
        raise NemoInterpreterError(f"NEMO NetCDF file not found: {path}")

    with xr.open_dataset(path) as dataset:
        time_index = _select_time_index(dataset, time)
        lat_name, lon_name = _lat_lon_names(dataset)
        grid = _nearest_grid_point(dataset, lat, lon, lat_name, lon_name)

        uo_name = _first_existing(dataset, NEMO_UO_NAMES)
        vo_name = _first_existing(dataset, NEMO_VO_NAMES)
        ssh_name = _first_existing(dataset, NEMO_SSH_NAMES, required=False)
        sst_name = _first_existing(dataset, NEMO_SST_NAMES, required=False)
        sal_name = _first_existing(dataset, NEMO_SALINITY_NAMES, required=False)

        uo = _point_value(dataset[uo_name], grid, time_index, lat_name, lon_name)
        vo = _point_value(dataset[vo_name], grid, time_index, lat_name, lon_name)
        ssh = _point_value(dataset[ssh_name], grid, time_index, lat_name, lon_name) if ssh_name else None
        sst = _point_value(dataset[sst_name], grid, time_index, lat_name, lon_name) if sst_name else None
        sal = _point_value(dataset[sal_name], grid, time_index, lat_name, lon_name) if sal_name else None

    # Calculate current speed in knots and flow direction
    current_speed_knots = sqrt(uo**2 + vo**2) * MPS_TO_KNOTS
    # Current flow is defined as "direction towards" in physical models, 
    # but wind is "direction from". We use wind_direction_cardinal for flow context.
    current_dir = wind_direction_cardinal(uo, vo)

    # Convert SST to Celsius if it looks like Kelvin
    sst_c = sst
    if sst is not None and sst > 100.0:
        sst_c = sst - 273.15

    return {
        "model": "nemo",
        "current_speed_knots": round(current_speed_knots, 2),
        "current_direction": current_dir,
        "source": str(path),
        "location": {
            "requested": {"lat": float(lat), "lon": float(lon)},
            "nearest_grid": grid,
        },
        "metrics": {
            "uo_mps": round(uo, 3),
            "vo_mps": round(vo, 3),
            "sea_surface_height_m": round(ssh, 3) if ssh is not None else None,
            "sea_surface_temperature_c": round(sst_c, 2) if sst_c is not None else None,
            "salinity_psu": round(sal, 2) if sal is not None else None,
        },
    }


def nearest_grid_point_nemo(nemo_path: str | Path, lat: float, lon: float) -> dict[str, Any]:
    """Find nearest index coordinates on the NEMO grid."""
    with xr.open_dataset(nemo_path) as dataset:
        lat_name, lon_name = _lat_lon_names(dataset)
        return _nearest_grid_point(dataset, lat, lon, lat_name, lon_name)


def get_nemo_route_summary(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    time: str | None,
    nemo_path: str | Path,
    samples: int = 8,
) -> dict[str, Any]:
    """Extract and summarize ocean current states along a route."""
    from processing.mariner_interpreter import sample_route_points

    route_points = sample_route_points(start_lat, start_lon, end_lat, end_lon, samples)
    sample_summaries = [
        get_nemo_summary(lat=pt["lat"], lon=point["lon"] if "lon" in point else pt["lon"], time=time, nemo_path=nemo_path)
        for pt in route_points
        for point in [pt]  # variable alias safety
    ]

    # Worst sampled point has maximum current speed
    worst = max(sample_summaries, key=lambda s: s["current_speed_knots"])

    return {
        "max_current_speed_knots": worst["current_speed_knots"],
        "worst_point": worst,
        "samples": sample_summaries,
        "sample_count": len(sample_summaries),
        "source": str(nemo_path),
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
        raise NemoInterpreterError("NEMO NetCDF is missing latitude/longitude coordinates.")
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

    # Subset depth if variable is 3D currents (depth, y, x)
    for depth_name in ("depth", "depthu", "depthv", "depthw", "z", "level"):
        if depth_name in selected.dims:
            selected = selected.isel({depth_name: 0})

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
        raise NemoInterpreterError(f"NEMO NetCDF is missing one of: {', '.join(names)}")
    return None
