"""Load atmospheric wind GRIB2 files into xarray Datasets.

Converts the raw GRIB2 output from any atmospheric fetcher (AROME,
HARMONIE, ECMWF) into a normalized xarray Dataset with standard
``latitude``, ``longitude``, ``u10``, ``v10`` variables.

This bridges the gap between the raw download and the grid_blender
spatial alignment step.
"""

from pathlib import Path

import numpy as np


def load_wind_dataset(dataset_path, provider_id=None):
    """Load a wind GRIB2 file and normalize to standard variable names.

    Parameters
    ----------
    dataset_path : str or Path
        Path to a GRIB2 file containing 10m wind data.
    provider_id : str, optional
        Provider identifier to select the right normalization rules.

    Returns
    -------
    xarray.Dataset
        Dataset with ``latitude``, ``longitude``, ``u10``, ``v10`` variables.
    """
    import xarray as xr

    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Wind dataset not found: {path}")

    # Try cfgrib first (for GRIB2 files)
    try:
        ds = xr.open_dataset(str(path), engine="cfgrib")
        return _normalize_wind_variables(ds, provider_id)
    except Exception:
        pass

    # Try netCDF4 fallback (in case file is NetCDF)
    try:
        ds = xr.open_dataset(str(path), engine="netcdf4")
        return _normalize_wind_variables(ds, provider_id)
    except Exception:
        pass

    # Try h5netcdf as last resort
    try:
        ds = xr.open_dataset(str(path), engine="h5netcdf")
        return _normalize_wind_variables(ds, provider_id)
    except Exception as error:
        raise RuntimeError(f"Cannot load wind dataset from {path}: {error}")


def _normalize_wind_variables(ds, provider_id=None):
    """Rename variables and coordinates to the PredSea standard.

    Standard names: latitude, longitude, u10, v10
    """
    # Coordinate normalization
    coord_renames = {}
    lat_name = _find_coord(ds, ("latitude", "lat", "y"))
    lon_name = _find_coord(ds, ("longitude", "lon", "x"))
    if lat_name and lat_name != "latitude":
        coord_renames[lat_name] = "latitude"
    if lon_name and lon_name != "longitude":
        coord_renames[lon_name] = "longitude"

    # Variable normalization — different providers use different names
    var_renames = {}
    u_name = _find_var(ds, ("u10", "10u", "U_COMPONENT_OF_WIND", "u_wind"))
    v_name = _find_var(ds, ("v10", "10v", "V_COMPONENT_OF_WIND", "v_wind"))
    gust_name = _find_var(ds, ("wind_gust", "i10fg", "WIND_SPEED_GUST", "gust"))

    if u_name and u_name != "u10":
        var_renames[u_name] = "u10"
    if v_name and v_name != "v10":
        var_renames[v_name] = "v10"
    if gust_name and gust_name != "wind_gust":
        var_renames[gust_name] = "wind_gust"

    renames = {**coord_renames, **var_renames}
    if renames:
        ds = ds.rename(renames)

    # Ensure latitude is in ascending order (some GRIB files are descending)
    if "latitude" in ds.coords and len(ds.latitude) > 1:
        if float(ds.latitude[0]) > float(ds.latitude[-1]):
            ds = ds.sortby("latitude")

    return ds


def _find_coord(ds, candidates):
    """Return the first matching coordinate name from candidates."""
    for name in candidates:
        if name in ds.coords:
            return name
    return None


def _find_var(ds, candidates):
    """Return the first matching variable name from candidates."""
    for name in candidates:
        if name in ds.data_vars:
            return name
    return None


def compute_wind_speed(ds):
    """Add a ``wind_speed`` variable computed from U and V components."""
    if "u10" in ds and "v10" in ds:
        ds["wind_speed"] = np.sqrt(ds["u10"] ** 2 + ds["v10"] ** 2)
        ds["wind_speed"].attrs.update(
            units="m s-1",
            long_name="10m wind speed",
        )
    return ds


def compute_wind_direction(ds):
    """Add a ``wind_direction`` variable (meteorological convention, degrees from)."""
    if "u10" in ds and "v10" in ds:
        ds["wind_direction"] = (np.degrees(np.arctan2(-ds["u10"], -ds["v10"])) + 360.0) % 360.0
        ds["wind_direction"].attrs.update(
            units="degrees",
            long_name="10m wind direction (from)",
        )
    return ds
