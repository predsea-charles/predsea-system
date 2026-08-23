#!/usr/bin/env python3
"""
Tests for PredSea ROMS Forecast Ingestor.
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

import roms_forecast_ingestor


@pytest.fixture
def mock_roms_file(tmp_path):
    roms_path = tmp_path / "roms_sample.nc"
    # Dimensions: ocean_time, s_rho, eta_rho, xi_rho
    dataset = xr.Dataset(
        data_vars={
            "u": (("ocean_time", "s_rho", "eta_rho", "xi_rho"), np.array([[[[-0.2, 0.4], [0.1, -0.3]]]])),
            "v": (("ocean_time", "s_rho", "eta_rho", "xi_rho"), np.array([[[[0.3, -0.1], [-0.4, 0.2]]]])),
            "temp": (("ocean_time", "s_rho", "eta_rho", "xi_rho"), np.array([[[[18.5, 19.0], [17.8, 18.2]]]])),
            "salt": (("ocean_time", "s_rho", "eta_rho", "xi_rho"), np.array([[[[37.2, 37.5], [37.1, 37.3]]]])),
            "zeta": (("ocean_time", "eta_rho", "xi_rho"), np.array([[[0.12, -0.05], [0.03, 0.08]]])),
            "lat_rho": (("eta_rho", "xi_rho"), np.array([[39.0, 39.0], [40.0, 40.0]])),
            "lon_rho": (("eta_rho", "xi_rho"), np.array([[2.0, 3.0], [2.0, 3.0]])),
        },
        coords={
            "ocean_time": np.array(["2026-06-24T12:00:00"], dtype="datetime64[ns]"),
            "s_rho": np.array([-1.0]),
        },
    )
    dataset.to_netcdf(roms_path)
    return roms_path


def test_utc_to_local_str():
    dt = datetime.datetime(2026, 6, 24, 12, 0, tzinfo=datetime.timezone.utc)
    local_str = roms_forecast_ingestor.utc_to_local_str(dt)
    assert local_str == "14:00"


def test_get_nearest_grid_indices():
    lats = xr.DataArray(np.array([[39.0, 39.0], [40.0, 40.0]]))
    lons = xr.DataArray(np.array([[2.0, 3.0], [2.0, 3.0]]))
    
    j, i = roms_forecast_ingestor.get_nearest_grid_indices(lats, lons, 39.1, 2.1)
    assert j == 0
    assert i == 0
    
    j, i = roms_forecast_ingestor.get_nearest_grid_indices(lats, lons, 39.9, 2.9)
    assert j == 1
    assert i == 1


def test_process_roms_forecast(mock_roms_file):
    rows = roms_forecast_ingestor.process_roms_forecast(
        str(mock_roms_file), run_date="2026-06-24", run_id="run-123"
    )
    
    assert len(rows) > 0
    
    # Check keys and mapping
    first_row = rows[0]
    assert first_row["schema_version"] == "predsea.validation.v1"
    assert first_row["record_type"] == "forecast"
    assert first_row["source_family"] == "ocean_forecast"
    assert first_row["forecast_source_id"] == "predsea_roms"
    assert first_row["resolution_km"] == 1.0
    
    # Assert variables are mapped
    variables = {r["variable"] for r in rows}
    assert "current_speed" in variables
    assert "current_direction" in variables
    assert "water_temperature" in variables
    assert "salinity" in variables
    assert "sea_level" in variables


def test_main_dry_run(mock_roms_file):
    args = [
        "--local-file", str(mock_roms_file),
        "--run-date", "2026-06-24",
        "--run-id", "test-run-123",
        "--dry-run"
    ]
    ret = roms_forecast_ingestor.main(args)
    assert ret == 0


def test_download_roms_file_from_gcs_not_found(monkeypatch):
    class MockStorageBucket:
        def list_blobs(self, prefix=""):
            return []

    class MockStorageClient:
        def bucket(self, name):
            return MockStorageBucket()

    monkeypatch.setattr(roms_forecast_ingestor.storage, "Client", MockStorageClient)
    
    success = roms_forecast_ingestor.download_roms_file_from_gcs(
        "bucket", "2026-06-24", "run-123", "local_file.nc"
    )
    assert success is False
