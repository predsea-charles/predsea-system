import importlib.util
from pathlib import Path

import numpy as np
import pytest
import xarray as xr


MODULE_PATH = Path(__file__).resolve().parents[1] / "humanintheloop" / "forecast_sources.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forecast_sources_native_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native_swan_dataset(timestamp_count=25):
    times = (
        np.arange(timestamp_count).astype("timedelta64[h]")
        + np.datetime64("2026-07-20T00:00:00")
    )
    shape = (timestamp_count, 2, 3)
    return xr.Dataset(
        {
            "significant_wave_height": (
                ("time", "latitude", "longitude"), np.full(shape, 1.2)
            ),
            "mean_wave_direction": (
                ("time", "latitude", "longitude"), np.full(shape, 225.0)
            ),
            "peak_wave_period": (
                ("time", "latitude", "longitude"), np.full(shape, 7.5)
            ),
        },
        coords={
            "time": times,
            "latitude": [37.5, 41.5],
            "longitude": [0.5, 3.0, 5.5],
        },
        attrs={"source": "SWAN version 41.51AB"},
    )


def test_adapt_native_swan_for_publication_writes_route_schema(tmp_path):
    module = load_module()
    source = tmp_path / "native.nc"
    destination = tmp_path / "predsea_waves.nc"
    native_swan_dataset().to_netcdf(source)

    report = module.adapt_native_swan_for_publication(source, destination, expected_hours=24)

    assert report["timestamp_count"] == 25
    with xr.open_dataset(destination) as dataset:
        assert {"VHM0", "VMDR", "VTPK"} <= set(dataset.data_vars)
        assert dataset.attrs["provider"] == "predsea_swan"
        assert dataset.sizes["time"] == 25


def test_adapt_native_swan_for_publication_rejects_incomplete_timeline(tmp_path):
    module = load_module()
    source = tmp_path / "native.nc"
    native_swan_dataset(timestamp_count=24).to_netcdf(source)

    with pytest.raises(ValueError, match="24 timestamps; expected 25"):
        module.adapt_native_swan_for_publication(
            source, tmp_path / "out.nc", expected_hours=24
        )


def test_adapt_current_fallback_subsets_exact_native_timeline(tmp_path):
    module = load_module()
    times = np.arange(30).astype("timedelta64[h]") + np.datetime64("2026-07-20T00:00:00")
    source = tmp_path / "currents.nc"
    destination = tmp_path / "predsea_ocean.nc"
    xr.Dataset(
        {
            "uo": (("time", "latitude", "longitude"), np.full((30, 2, 2), 0.2)),
            "vo": (("time", "latitude", "longitude"), np.full((30, 2, 2), -0.1)),
        },
        coords={"time": times, "latitude": [38.0, 40.0], "longitude": [1.0, 4.0]},
    ).to_netcdf(source)

    report = module.adapt_current_fallback_for_publication(source, destination, times[:25])

    assert report["timestamp_count"] == 25
    with xr.open_dataset(destination) as dataset:
        assert dataset.sizes["time"] == 25
        assert dataset.attrs["provider"] == "copernicus"


def test_adapt_current_fallback_rejects_time_mismatch(tmp_path):
    module = load_module()
    source = tmp_path / "currents.nc"
    available = np.arange(24).astype("timedelta64[h]") + np.datetime64("2026-07-20T00:00:00")
    required = np.arange(25).astype("timedelta64[h]") + np.datetime64("2026-07-20T00:00:00")
    xr.Dataset(
        {
            "uo": (("time", "latitude", "longitude"), np.zeros((24, 1, 1))),
            "vo": (("time", "latitude", "longitude"), np.zeros((24, 1, 1))),
        },
        coords={"time": available, "latitude": [39.0], "longitude": [2.0]},
    ).to_netcdf(source)

    with pytest.raises(ValueError, match="does not cover native SWAN time"):
        module.adapt_current_fallback_for_publication(source, tmp_path / "out.nc", required)
