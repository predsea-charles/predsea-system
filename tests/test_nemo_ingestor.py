#!/usr/bin/env python3
"""
Tests for PredSea NEMO Forecast Ingestor.
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

import nemo_forecast_ingestor


@pytest.fixture
def mock_nemo_file(tmp_path):
    nemo_path = tmp_path / "nemo_sample.nc"
    # Dimensions: time_counter, lev, y, x
    dataset = xr.Dataset(
        data_vars={
            "uo": (("time_counter", "lev", "y", "x"), np.array([[[[-0.15, 0.35], [0.12, -0.25]]]])),
            "vo": (("time_counter", "lev", "y", "x"), np.array([[[[0.25, -0.12], [-0.35, 0.18]]]])),
            "thetao": (("time_counter", "lev", "y", "x"), np.array([[[[18.2, 18.8], [17.5, 17.9]]]])),
            "so": (("time_counter", "lev", "y", "x"), np.array([[[[37.1, 37.4], [37.0, 37.2]]]])),
            "zos": (("time_counter", "y", "x"), np.array([[[0.10, -0.04], [0.02, 0.07]]])),
            "nav_lat": (("y", "x"), np.array([[39.0, 39.0], [40.0, 40.0]])),
            "nav_lon": (("y", "x"), np.array([[2.0, 3.0], [2.0, 3.0]])),
        },
        coords={
            "time_counter": np.array(["2026-06-24T12:00:00"], dtype="datetime64[ns]"),
            "lev": np.array([-1.0]),
        },
    )
    dataset.to_netcdf(nemo_path)
    return nemo_path


def test_utc_to_local_str():
    dt = datetime.datetime(2026, 6, 24, 12, 0, tzinfo=datetime.timezone.utc)
    local_str = nemo_forecast_ingestor.utc_to_local_str(dt)
    assert local_str == "14:00"


def test_get_nearest_grid_indices():
    lats = xr.DataArray(np.array([[39.0, 39.0], [40.0, 40.0]]))
    lons = xr.DataArray(np.array([[2.0, 3.0], [2.0, 3.0]]))
    
    j, i = nemo_forecast_ingestor.get_nearest_grid_indices(lats, lons, 39.1, 2.1)
    assert j == 0
    assert i == 0
    
    j, i = nemo_forecast_ingestor.get_nearest_grid_indices(lats, lons, 39.9, 2.9)
    assert j == 1
    assert i == 1


def test_process_nemo_forecast(mock_nemo_file):
    rows = nemo_forecast_ingestor.process_nemo_forecast(
        str(mock_nemo_file), run_date="2026-06-24", run_id="run-123"
    )
    
    assert len(rows) > 0
    
    # Check keys and mapping
    first_row = rows[0]
    assert first_row["schema_version"] == "predsea.validation.v1"
    assert first_row["record_type"] == "forecast"
    assert first_row["source_family"] == "ocean_forecast"
    assert first_row["forecast_source_id"] == "predsea_nemo"
    assert first_row["resolution_km"] == 1.0
    
    # Assert variables are mapped
    variables = {r["variable"] for r in rows}
    assert "current_speed" in variables
    assert "current_direction" in variables
    assert "water_temperature" in variables
    assert "salinity" in variables
    assert "sea_level" in variables


def test_main_dry_run(mock_nemo_file):
    args = [
        "--local-file", str(mock_nemo_file),
        "--run-date", "2026-06-24",
        "--run-id", "test-run-123",
        "--dry-run"
    ]
    ret = nemo_forecast_ingestor.main(args)
    assert ret == 0


def test_download_nemo_file_from_gcs_not_found(monkeypatch):
    class MockStorageBucket:
        def list_blobs(self, prefix=""):
            return []

    class MockStorageClient:
        def bucket(self, name):
            return MockStorageBucket()

    monkeypatch.setattr(nemo_forecast_ingestor.storage, "Client", MockStorageClient)
    
    success = nemo_forecast_ingestor.download_nemo_file_from_gcs(
        "bucket", "2026-06-24", "run-123", "local_file.nc"
    )
    assert success is False
