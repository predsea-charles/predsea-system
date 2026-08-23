"""Tests for wind loader and grid blending pipeline."""

import numpy as np
import xarray as xr

import wind_loader


def test_normalize_wind_variables_renames_ecmwf_style():
    ds = xr.Dataset(
        {
            "10u": (("latitude", "longitude"), [[1.0, 2.0]]),
            "10v": (("latitude", "longitude"), [[0.5, 1.0]]),
            "i10fg": (("latitude", "longitude"), [[3.0, 4.0]]),
        },
        coords={"latitude": [39.0], "longitude": [2.0, 2.5]},
    )
    normalized = wind_loader._normalize_wind_variables(ds, "ecmwf_open_data")
    assert "u10" in normalized.data_vars
    assert "v10" in normalized.data_vars
    assert "wind_gust" in normalized.data_vars


def test_normalize_wind_variables_keeps_standard_names():
    ds = xr.Dataset(
        {
            "u10": (("latitude", "longitude"), [[1.0]]),
            "v10": (("latitude", "longitude"), [[0.5]]),
        },
        coords={"latitude": [39.0], "longitude": [2.0]},
    )
    normalized = wind_loader._normalize_wind_variables(ds)
    assert "u10" in normalized.data_vars
    assert "v10" in normalized.data_vars


def test_normalize_renames_lat_lon_coords():
    ds = xr.Dataset(
        {
            "u10": (("lat", "lon"), [[1.0]]),
            "v10": (("lat", "lon"), [[0.5]]),
        },
        coords={"lat": [39.0], "lon": [2.0]},
    )
    normalized = wind_loader._normalize_wind_variables(ds)
    assert "latitude" in normalized.coords
    assert "longitude" in normalized.coords


def test_compute_wind_speed():
    ds = xr.Dataset(
        {
            "u10": (("latitude", "longitude"), [[3.0]]),
            "v10": (("latitude", "longitude"), [[4.0]]),
        },
        coords={"latitude": [39.0], "longitude": [2.0]},
    )
    result = wind_loader.compute_wind_speed(ds)
    assert "wind_speed" in result.data_vars
    assert np.isclose(float(result["wind_speed"].values[0, 0]), 5.0)


def test_compute_wind_direction():
    ds = xr.Dataset(
        {
            "u10": (("latitude", "longitude"), [[0.0]]),
            "v10": (("latitude", "longitude"), [[-1.0]]),
        },
        coords={"latitude": [39.0], "longitude": [2.0]},
    )
    result = wind_loader.compute_wind_direction(ds)
    assert "wind_direction" in result.data_vars
    # Wind from the north (v=-1, u=0) should give 0 degrees
    direction = float(result["wind_direction"].values[0, 0])
    assert np.isclose(direction, 0.0, atol=1.0) or np.isclose(direction, 360.0, atol=1.0)
