#!/usr/bin/env python3
"""
Tests for PredSea SWAN Forecast Ingestor.
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import swan_forecast_ingestor


@pytest.fixture
def mock_swan_file(tmp_path):
    swan_path = tmp_path / "swan_sample.nc"
    # Dimensions: time, lat, lon
    dataset = xr.Dataset(
        data_vars={
            "hs": (("time", "lat", "lon"), np.array([[[1.2, 1.5], [0.8, 1.0]]])),
            "tps": (("time", "lat", "lon"), np.array([[[6.5, 7.0], [5.8, 6.2]]])),
            "dir": (("time", "lat", "lon"), np.array([[[120.0, 135.0], [110.0, 125.0]]])),
            "latitude": (("lat", "lon"), np.array([[39.0, 39.0], [40.0, 40.0]])),
            "longitude": (("lat", "lon"), np.array([[2.0, 3.0], [2.0, 3.0]])),
        },
        coords={
            "time": np.array(["2026-06-24T12:00:00"], dtype="datetime64[ns]"),
        },
    )
    dataset.to_netcdf(swan_path)
    return swan_path


def test_utc_to_local_str():
    dt = datetime.datetime(2026, 6, 24, 12, 0, tzinfo=datetime.timezone.utc)
    local_str = swan_forecast_ingestor.utc_to_local_str(dt)
    assert local_str == "14:00"


def test_get_nearest_grid_indices():
    lats = xr.DataArray(np.array([[39.0, 39.0], [40.0, 40.0]]))
    lons = xr.DataArray(np.array([[2.0, 3.0], [2.0, 3.0]]))
    
    j, i = swan_forecast_ingestor.get_nearest_grid_indices(lats, lons, 39.1, 2.1)
    assert j == 0
    assert i == 0
    
    j, i = swan_forecast_ingestor.get_nearest_grid_indices(lats, lons, 39.9, 2.9)
    assert j == 1
    assert i == 1


def test_process_swan_forecast(mock_swan_file):
    rows = swan_forecast_ingestor.process_swan_forecast(
        str(mock_swan_file), run_date="2026-06-24", run_id="run-123"
    )
    
    assert len(rows) > 0
    
    # Check keys and mapping
    first_row = rows[0]
    assert first_row["schema_version"] == "predsea.validation.v1"
    assert first_row["record_type"] == "forecast"
    assert first_row["source_family"] == "wave_forecast"
    assert first_row["forecast_source_id"] == "predsea_swan"
    assert first_row["resolution_km"] == 1.0
    
    # Assert variables are mapped
    variables = {r["variable"] for r in rows}
    assert "wave_height" in variables
    assert "wave_period" in variables
    assert "wave_direction" in variables


def test_main_dry_run(mock_swan_file):
    args = [
        "--local-file", str(mock_swan_file),
        "--run-date", "2026-06-24",
        "--run-id", "test-run-123",
        "--dry-run"
    ]
    ret = swan_forecast_ingestor.main(args)
    assert ret == 0


def test_download_swan_file_from_gcs_not_found(monkeypatch):
    class MockStorageBucket:
        def list_blobs(self, prefix=""):
            return []

    class MockStorageClient:
        def bucket(self, name):
            return MockStorageBucket()

    monkeypatch.setattr(swan_forecast_ingestor.storage, "Client", MockStorageClient)
    
    success = swan_forecast_ingestor.download_swan_file_from_gcs(
        "bucket", "2026-06-24", "run-123", "local_file.nc"
    )
    assert success is False
