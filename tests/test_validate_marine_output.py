from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr

from scripts.validate_marine_output import validate


REGION = Path("simulation/marine/regions/balearic_1km.json")


def _coords(hours: int = 6):
    return {
        "time": np.arange(
            np.datetime64("2026-07-16T00"),
            np.datetime64(f"2026-07-16T{hours + 1:02d}"),
            np.timedelta64(1, "h"),
        ),
        "latitude": np.array([37.5, 39.5, 41.5], dtype=np.float32),
        "longitude": np.array([0.5, 3.0, 5.5], dtype=np.float32),
    }


def test_valid_swan_output_passes(tmp_path):
    coords = _coords()
    shape = (len(coords["time"]), 3, 3)
    dataset = xr.Dataset(
        {
            "hs": (("time", "latitude", "longitude"), np.full(shape, 1.2)),
            "tp": (("time", "latitude", "longitude"), np.full(shape, 7.0)),
            "dir": (("time", "latitude", "longitude"), np.full(shape, 240.0)),
        },
        coords=coords,
    )
    path = tmp_path / "predsea_swan.nc"
    dataset.to_netcdf(path)

    report = validate(path, "swan", REGION, 6)

    assert report["status"] == "succeeded"
    assert report["timestamp_count"] == 7
    assert report["variables"]["significant_wave_height"]["source_name"] == "hs"


def test_croco_missing_salinity_fails(tmp_path):
    coords = _coords()
    shape = (len(coords["time"]), 3, 3)
    dataset = xr.Dataset(
        {
            "uo": (("time", "latitude", "longitude"), np.zeros(shape)),
            "vo": (("time", "latitude", "longitude"), np.zeros(shape)),
            "thetao": (("time", "latitude", "longitude"), np.full(shape, 20.0)),
            "zos": (("time", "latitude", "longitude"), np.zeros(shape)),
        },
        coords=coords,
    )
    path = tmp_path / "predsea_croco.nc"
    dataset.to_netcdf(path)

    report = validate(path, "croco", REGION, 6)

    assert report["status"] == "failed"
    assert "missing required variable sea_surface_salinity" in report["errors"]


def test_wrong_timeline_and_physical_range_fail(tmp_path):
    coords = _coords(hours=5)
    shape = (len(coords["time"]), 3, 3)
    dataset = xr.Dataset(
        {"hs": (("time", "latitude", "longitude"), np.full(shape, 99.0))},
        coords=coords,
    )
    path = tmp_path / "predsea_swan.nc"
    dataset.to_netcdf(path)

    report = validate(path, "swan", REGION, 6)

    assert report["status"] == "failed"
    assert "expected 7 timestamps, found 6" in report["errors"]
    assert any("exceeds" in error for error in report["errors"])
