from __future__ import annotations

from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from processing.mariner_interpreter import MPS_TO_KNOTS, wind_direction_cardinal


GFS_U10_NAMES = ("u10", "10u", "UGRD_10maboveground", "u")
GFS_V10_NAMES = ("v10", "10v", "VGRD_10maboveground", "v")
GFS_PRESSURE_NAMES = ("msl", "prmsl", "PRMSL_meansealevel", "sp")


class GfsInterpreterError(ValueError):
    """Raised when a GFS NetCDF file cannot be interpreted."""


def get_gfs_summary(
    lat: float,
    lon: float,
    time: str | None,
    gfs_path: str | Path,
) -> dict[str, Any]:
    path = Path(gfs_path)
    with xr.open_dataset(path) as dataset:
        time_index = _select_time_index(dataset, time)
        lat_name, lon_name = _lat_lon_names(dataset)
        grid = _nearest_grid_point(dataset, lat, lon, lat_name, lon_name)
        u_name = _first_existing(dataset, GFS_U10_NAMES)
        v_name = _first_existing(dataset, GFS_V10_NAMES)
        pressure_name = _first_existing(dataset, GFS_PRESSURE_NAMES, required=False)
        u10 = _point_value(dataset[u_name], grid, time_index, lat_name, lon_name)
        v10 = _point_value(dataset[v_name], grid, time_index, lat_name, lon_name)
        pressure = (
            _point_value(dataset[pressure_name], grid, time_index, lat_name, lon_name)
            if pressure_name
            else None
        )

    wind_knots = round(sqrt(u10**2 + v10**2) * MPS_TO_KNOTS)
    return {
        "model": "gfs",
        "wind_knots": int(wind_knots),
        "direction": wind_direction_cardinal(u10, v10),
        "source": str(path),
        "location": {
            "requested": {"lat": float(lat), "lon": float(lon)},
            "nearest_grid": grid,
        },
        "metrics": {
            "u10_mps": round(u10, 2),
            "v10_mps": round(v10, 2),
            "pressure_hpa": round(pressure / 100.0, 2) if pressure is not None else None,
        },
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
    for name in ("time", "valid_time", "Time"):
        if name in dataset.coords or name in dataset.dims:
            return name
    return None


def _lat_lon_names(dataset: xr.Dataset) -> tuple[str, str]:
    lat_name = next((name for name in ("latitude", "lat", "XLAT") if name in dataset), None)
    lon_name = next((name for name in ("longitude", "lon", "XLONG") if name in dataset), None)
    if lat_name is None or lon_name is None:
        raise GfsInterpreterError("GFS NetCDF needs latitude/longitude coordinates.")
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
    time_name = next((name for name in ("time", "valid_time", "Time") if name in selected.dims), None)
    if time_name:
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
        raise GfsInterpreterError(f"GFS NetCDF is missing one of: {', '.join(names)}")
    return None
