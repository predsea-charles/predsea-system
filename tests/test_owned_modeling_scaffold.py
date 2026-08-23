from __future__ import annotations

from pathlib import Path
import numpy as np
import pytest
import xarray as xr

from processing.nemo_interpreter import (
    get_nemo_summary,
    nearest_grid_point_nemo,
    get_nemo_route_summary,
    NemoInterpreterError,
)
from processing.swan_interpreter import (
    get_swan_summary,
    nearest_grid_point_swan,
    get_swan_route_summary,
    SwanInterpreterError,
)
from processing.marine_fusion import (
    calculate_bearing,
    get_comfort_level,
    calculate_fuel_penalty,
    fuse_marine_conditions,
    fuse_route_conditions,
)


@pytest.fixture
def mock_nemo_file(tmp_path):
    nemo_path = tmp_path / "nemo_sample.nc"
    # Dimensions: time_counter, depth, nav_lat, nav_lon
    dataset = xr.Dataset(
        data_vars={
            "uo": (("time_counter", "depth", "nav_lat", "nav_lon"), np.array([[[[-0.2, 0.4], [0.1, -0.3]]]])),
            "vo": (("time_counter", "depth", "nav_lat", "nav_lon"), np.array([[[[0.3, -0.1], [-0.4, 0.2]]]])),
            "zos": (("time_counter", "nav_lat", "nav_lon"), np.array([[[0.12, -0.05], [0.03, 0.08]]])),
            "tos": (("time_counter", "nav_lat", "nav_lon"), np.array([[[291.5, 292.0], [290.8, 291.2]]])), # SST in Kelvin
            "sos": (("time_counter", "nav_lat", "nav_lon"), np.array([[[37.2, 37.5], [37.1, 37.3]]])),
        },
        coords={
            "time_counter": np.array(["2026-06-24T12:00:00"], dtype="datetime64[ns]"),
            "nav_lat": np.array([39.0, 40.0]),
            "nav_lon": np.array([2.0, 3.0]),
            "depth": np.array([0.5]),
        },
    )
    dataset.to_netcdf(nemo_path)
    return nemo_path


@pytest.fixture
def mock_swan_file(tmp_path):
    swan_path = tmp_path / "swan_sample.nc"
    # Dimensions: time, latitude, longitude
    dataset = xr.Dataset(
        data_vars={
            "hs": (("time", "latitude", "longitude"), np.array([[[0.5, 1.2], [1.8, 2.5]]])),
            "tpp": (("time", "latitude", "longitude"), np.array([[[5.5, 7.2], [6.8, 8.5]]])),
            "dir": (("time", "latitude", "longitude"), np.array([[[180.0, 225.0], [270.0, 315.0]]])),
        },
        coords={
            "time": np.array(["2026-06-24T12:00:00"], dtype="datetime64[ns]"),
            "latitude": np.array([39.0, 40.0]),
            "longitude": np.array([2.0, 3.0]),
        },
    )
    dataset.to_netcdf(swan_path)
    return swan_path


@pytest.fixture
def mock_wrf_file(tmp_path):
    wrf_path = tmp_path / "wrf_sample.nc"
    # Dimensions: Time, south_north, west_east
    dataset = xr.Dataset(
        data_vars={
            "U10": (("Time", "south_north", "west_east"), np.array([[[-5.0, 5.0], [-2.0, 2.0]]])),
            "V10": (("Time", "south_north", "west_east"), np.array([[[5.0, -5.0], [2.0, -2.0]]])),
            "T2": (("Time", "south_north", "west_east"), np.array([[[295.0, 296.0], [294.0, 295.0]]])),
            "PSFC": (("Time", "south_north", "west_east"), np.array([[[101200.0, 101300.0], [101100.0, 101200.0]]])),
            "HGT": (("Time", "south_north", "west_east"), np.array([[[0.0, 10.0], [5.0, 0.0]]])),
            "XLAT": (("Time", "south_north", "west_east"), np.array([[[39.0, 39.0], [40.0, 40.0]]])),
            "XLONG": (("Time", "south_north", "west_east"), np.array([[[2.0, 3.0], [2.0, 3.0]]])),
        },
        coords={
            "Time": np.array([0]),
        },
    )
    dataset.to_netcdf(wrf_path)
    return wrf_path


def test_nemo_interpreter_extracts_correct_values(mock_nemo_file):
    summary = get_nemo_summary(39.2, 2.1, "2026-06-24T12:00:00", mock_nemo_file)

    assert summary["model"] == "nemo"
    assert summary["current_speed_knots"] > 0
    assert summary["current_direction"] in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
    assert summary["metrics"]["uo_mps"] == -0.2
    assert summary["metrics"]["vo_mps"] == 0.3
    assert summary["metrics"]["sea_surface_height_m"] == 0.12
    # Verify Kelvin-to-Celsius conversion: 291.5 - 273.15 = 18.35
    assert abs(summary["metrics"]["sea_surface_temperature_c"] - 18.35) < 0.01
    assert summary["metrics"]["salinity_psu"] == 37.2


def test_nemo_interpreter_nearest_point(mock_nemo_file):
    grid = nearest_grid_point_nemo(mock_nemo_file, 39.8, 2.9)
    assert grid["lat"] == 40.0
    assert grid["lon"] == 3.0


def test_nemo_route_summary(mock_nemo_file):
    route_sum = get_nemo_route_summary(39.0, 2.0, 40.0, 3.0, "2026-06-24T12:00:00", mock_nemo_file, samples=4)
    assert route_sum["sample_count"] == 4
    assert len(route_sum["samples"]) == 4
    assert route_sum["max_current_speed_knots"] == max(s["current_speed_knots"] for s in route_sum["samples"])


def test_nemo_interpreter_file_not_found():
    with pytest.raises(NemoInterpreterError):
        get_nemo_summary(39.0, 2.0, None, "non_existent_file.nc")


def test_swan_interpreter_extracts_correct_values(mock_swan_file):
    summary = get_swan_summary(39.9, 2.8, "2026-06-24T12:00:00", mock_swan_file)

    assert summary["model"] == "swan"
    assert summary["significant_wave_height_m"] == 2.5
    assert summary["peak_wave_period_s"] == 8.5
    assert summary["wave_direction_degrees"] == 315.0
    assert summary["wave_direction_cardinal"] == "NW"


def test_swan_interpreter_nearest_point(mock_swan_file):
    grid = nearest_grid_point_swan(mock_swan_file, 39.1, 2.2)
    assert grid["lat"] == 39.0
    assert grid["lon"] == 2.0


def test_swan_route_summary(mock_swan_file):
    route_sum = get_swan_route_summary(39.0, 2.0, 40.0, 3.0, "2026-06-24T12:00:00", mock_swan_file, samples=3)
    assert route_sum["sample_count"] == 3
    assert route_sum["max_wave_height_m"] == max(s["significant_wave_height_m"] for s in route_sum["samples"])


def test_swan_interpreter_file_not_found():
    with pytest.raises(SwanInterpreterError):
        get_swan_summary(39.0, 2.0, None, "non_existent_file.nc")


def test_marine_fusion_math():
    # 1. Bearings math
    assert round(calculate_bearing(39.0, 2.0, 39.0, 3.0), 1) == 89.7
    assert round(calculate_bearing(39.0, 2.0, 40.0, 2.0), 1) == 0.0

    # 2. Comfort level
    assert get_comfort_level(0.4, 0.2) == "comfortable"
    assert get_comfort_level(1.0, 0.2) == "moderate"
    assert get_comfort_level(0.4, 0.8) == "moderate"
    assert get_comfort_level(1.8, 1.5) == "rough"
    assert get_comfort_level(2.5, 0.2) == "high_risk"
    assert get_comfort_level(0.4, 2.2) == "high_risk"

    # 3. Fuel Penalty
    # No bearing -> no opposing current penalty (only waves)
    assert calculate_fuel_penalty(0.0, 0.0, 0.0, None) == 1.0
    # Waves = 3.0m -> max +50% wave penalty -> 1.5
    assert calculate_fuel_penalty(3.0, 0.0, 0.0, None) == 1.5
    # Bearing = 0 deg (northward travel), currents vo = -2.0 m/s (headwind) -> max +30% current penalty -> 1.3
    # Opposing current knots = 2.0 m/s * 1.94384 = 3.887 knots
    assert calculate_fuel_penalty(0.0, 0.0, -2.0, 0.0) == 1.3
    # Combined current + wave penalty: 1.0 + 0.3 + 0.5 = 1.8
    assert calculate_fuel_penalty(3.0, 0.0, -2.0, 0.0) == 1.8


def test_fuse_marine_conditions_end_to_end(mock_wrf_file, mock_nemo_file, mock_swan_file):
    # Coordinate: 39.0, 2.0
    sum_data = fuse_marine_conditions(
        lat=39.0,
        lon=2.0,
        time="2026-06-24T12:00:00",
        wrf_path=mock_wrf_file,
        nemo_path=mock_nemo_file,
        swan_path=mock_swan_file,
        travel_bearing=45.0,
    )

    assert sum_data["comfort_status"] == "moderate" # waves=0.5m, currents=0.70kt (uo=-0.2, vo=0.3)
    assert sum_data["fuel_penalty"] > 1.0
    assert "Winds are" in sum_data["captain_summary"]
    assert "uo_mps" in sum_data["currents"]
    assert "significant_height_m" in sum_data["waves"]


def test_fuse_route_conditions_end_to_end(mock_wrf_file, mock_nemo_file, mock_swan_file):
    route_sum = fuse_route_conditions(
        start_lat=39.0,
        start_lon=2.0,
        end_lat=40.0,
        end_lon=3.0,
        time="2026-06-24T12:00:00",
        wrf_path=mock_wrf_file,
        nemo_path=mock_nemo_file,
        swan_path=mock_swan_file,
        samples=4,
    )

    assert route_sum["sample_count"] == 4
    assert route_sum["comfort_status"] == "high_risk" # worst point coordinates has waves=2.5m (high_risk)
    assert route_sum["average_fuel_penalty"] > 1.0
    assert "worst_segment" in route_sum
    assert "expected average fuel penalty" in route_sum["route_summary"].lower()
