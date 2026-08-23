from __future__ import annotations

import datetime as dt
import numpy as np
import xarray as xr

from scripts.fetch_native_marine_forcing import validate_file


def test_validate_file_requires_depth_and_complete_timeline(tmp_path):
    path = tmp_path / "currents.nc"
    xr.Dataset(
        {
            "uo": (
                ("time", "depth", "latitude", "longitude"),
                np.zeros((7, 2, 2, 2)),
            ),
            "vo": (
                ("time", "depth", "latitude", "longitude"),
                np.zeros((7, 2, 2, 2)),
            ),
        },
        coords={
            "time": np.arange(
                np.datetime64("2026-07-16T00"),
                np.datetime64("2026-07-16T07"),
                np.timedelta64(1, "h"),
            ),
            "depth": [1.0, 10.0],
            "latitude": [37.5, 41.5],
            "longitude": [0.5, 5.5],
        },
    ).to_netcdf(path)

    report = validate_file(
        path,
        ["uo", "vo", "depth", "time"],
        7,
        expected_start=dt.datetime(2026, 7, 16, tzinfo=dt.timezone.utc),
        expected_end=dt.datetime(2026, 7, 16, 6, tzinfo=dt.timezone.utc),
    )

    assert report["status"] == "succeeded"
    assert report["depth_count"] == 2
    assert report["timestamp_count"] == 7


def test_validate_file_rejects_timezone_shifted_timeline(tmp_path):
    path = tmp_path / "waves.nc"
    xr.Dataset(
        {"VHM0": (("time",), np.ones(7))},
        coords={
            "time": np.arange(
                np.datetime64("2026-07-15T22"),
                np.datetime64("2026-07-16T05"),
                np.timedelta64(1, "h"),
            )
        },
    ).to_netcdf(path)

    report = validate_file(
        path,
        ["VHM0", "time"],
        7,
        expected_start=dt.datetime(2026, 7, 16, tzinfo=dt.timezone.utc),
        expected_end=dt.datetime(2026, 7, 16, 6, tzinfo=dt.timezone.utc),
    )

    assert report["status"] == "failed"
    assert any("expected first timestamp" in error for error in report["errors"])


def test_validate_file_rejects_surface_only_current_file(tmp_path):
    path = tmp_path / "currents.nc"
    xr.Dataset(
        {
            "uo": (("time", "latitude", "longitude"), np.zeros((7, 2, 2))),
            "vo": (("time", "latitude", "longitude"), np.zeros((7, 2, 2))),
        },
        coords={
            "time": range(7),
            "latitude": [37.5, 41.5],
            "longitude": [0.5, 5.5],
        },
    ).to_netcdf(path)

    report = validate_file(path, ["uo", "vo", "depth", "time"], 7)

    assert report["status"] == "failed"
    assert report["depth_count"] == 0
    assert report["errors"] == ["missing fields/dimensions: depth"]
