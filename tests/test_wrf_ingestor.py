#!/usr/bin/env python3
"""
Tests for PredSea WRF Forecast Ingestor.
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

import wrf_forecast_ingestor


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
            "XLAT": (("Time", "south_north", "west_east"), np.array([[[39.0, 39.0], [40.0, 40.0]]])),
            "XLONG": (("Time", "south_north", "west_east"), np.array([[[2.0, 3.0], [2.0, 3.0]]])),
            "SWDOWN": (("Time", "south_north", "west_east"), np.array([[[200.0, 300.0], [100.0, 0.0]]])),
        },
        coords={
            "Time": np.array([0]),
        },
    )
    dataset.to_netcdf(wrf_path)
    return wrf_path


def test_utc_to_local_str():
    dt = datetime.datetime(2026, 6, 24, 12, 0, tzinfo=datetime.timezone.utc)
    local_str = wrf_forecast_ingestor.utc_to_local_str(dt)
    # Europe/Madrid is UTC+2 in June (daylight saving time)
    assert local_str == "14:00"


def test_get_nearest_grid_indices():
    lats = xr.DataArray(np.array([[39.0, 39.0], [40.0, 40.0]]))
    lons = xr.DataArray(np.array([[2.0, 3.0], [2.0, 3.0]]))
    
    j, i = wrf_forecast_ingestor.get_nearest_grid_indices(lats, lons, 39.1, 2.1)
    assert j == 0
    assert i == 0
    
    j, i = wrf_forecast_ingestor.get_nearest_grid_indices(lats, lons, 39.9, 2.9)
    assert j == 1
    assert i == 1


def test_process_wrf_forecast(mock_wrf_file):
    rows = wrf_forecast_ingestor.process_wrf_forecast(
        str(mock_wrf_file), run_date="2026-06-24", run_id="run-123"
    )
    
    assert len(rows) > 0
    
    # Check that keys are conformant
    first_row = rows[0]
    assert first_row["schema_version"] == "predsea.validation.v1"
    assert first_row["record_type"] == "forecast"
    assert first_row["source_family"] == "atmosphere"
    assert first_row["forecast_source_id"] == "predsea_wrf"
    assert first_row["resolution_km"] == 1.0
    assert first_row["forecast_source_label"] == "PredSea D03 1km"
    
    # Check specific variable types are present
    variables = {r["variable"] for r in rows}
    assert "wind_speed" in variables
    assert "wind_direction" in variables
    assert "air_temperature" in variables
    assert "sea_level_pressure" in variables
    assert "solar_radiation" in variables
    
    # Find wind speed for a specific coordinate
    # The nearest grid point to Palmer (lat=39.55, lon=2.63 - approx in Palma region)
    # is checked. Let's check some values.
    temp_rows = [r for r in rows if r["variable"] == "air_temperature"]
    assert len(temp_rows) > 0
    for r in temp_rows:
        # T2 values are either 294, 295, 296 Kelvin -> converted to Celsius
        # 294K = 20.85C, 295K = 21.85C, 296K = 22.85C
        assert 20.0 < r["value"] < 24.0


def test_process_wrf_forecast_reports_native_three_km_resolution(mock_wrf_file):
    with xr.open_dataset(mock_wrf_file) as source:
        dataset = source.load()
    dataset.attrs["DX"] = 3000.0
    dataset.to_netcdf(mock_wrf_file, mode="w")

    rows = wrf_forecast_ingestor.process_wrf_forecast(
        str(mock_wrf_file), run_date="2026-06-24", run_id="run-3km", domain_id="d05"
    )

    assert rows[0]["resolution_km"] == 3.0
    assert rows[0]["forecast_source_label"] == "PredSea D05 3km"


def test_main_dry_run(mock_wrf_file):
    args = [
        "--local-file", str(mock_wrf_file),
        "--run-date", "2026-06-24",
        "--run-id", "test-run-123",
        "--dry-run"
    ]
    ret = wrf_forecast_ingestor.main(args)
    assert ret == 0


def test_download_wrf_files_from_gcs_not_found(monkeypatch, tmp_path):
    class MockStorageBlob:
        def __init__(self, name):
            self.name = name

    class MockStorageBucket:
        def list_blobs(self, prefix=""):
            return []

    class MockStorageClient:
        def bucket(self, name):
            return MockStorageBucket()

    monkeypatch.setattr(wrf_forecast_ingestor.storage, "Client", MockStorageClient)
    
    downloaded = wrf_forecast_ingestor.download_wrf_files_from_gcs(
        "bucket", "2026-06-24", "run-123", tmp_path
    )
    assert downloaded == []


def test_download_wrf_files_from_gcs_combines_all_hourly_outputs(monkeypatch, tmp_path):
    source_paths = []
    for hour, speed in enumerate((2.0, 4.0, 6.0)):
        source_path = tmp_path / f"source-{hour}.nc"
        xr.Dataset(
            {
                "U10": (("Time", "south_north", "west_east"), np.array([[[speed]]])),
                "V10": (("Time", "south_north", "west_east"), np.array([[[0.0]]])),
                "XLAT": (("Time", "south_north", "west_east"), np.array([[[39.0]]])),
                "XLONG": (("Time", "south_north", "west_east"), np.array([[[2.0]]])),
                "FULL_3D_STATE": (
                    ("Time", "bottom_top", "south_north", "west_east"),
                    np.array([[[[999.0]]]]),
                ),
            },
            coords={"Time": [hour]},
        ).to_netcdf(source_path)
        source_paths.append(source_path)

    class MockStorageBlob:
        def __init__(self, name, source_path):
            self.name = name
            self.source_path = source_path

        def download_to_filename(self, destination):
            Path(destination).write_bytes(self.source_path.read_bytes())

    blobs = [
        MockStorageBlob(
            f"predictions/2026-07-16/runs/run-123/wrfout_d02_2026-07-16_{hour:02d}:00:00",
            source_path,
        )
        for hour, source_path in reversed(list(enumerate(source_paths)))
    ]

    class MockStorageBucket:
        def list_blobs(self, prefix=""):
            return blobs

    class MockStorageClient:
        def bucket(self, name):
            return MockStorageBucket()

    monkeypatch.setattr(wrf_forecast_ingestor.storage, "Client", MockStorageClient)

    downloaded = wrf_forecast_ingestor.download_wrf_files_from_gcs(
        "bucket", "2026-07-16", "run-123", tmp_path / "combined"
    )

    assert downloaded == [("d02", tmp_path / "combined" / "wrf_d02.nc")]
    with xr.open_dataset(downloaded[0][1], decode_times=False) as combined:
        assert combined.sizes["Time"] == 3
        assert combined["U10"].values[:, 0, 0].tolist() == [2.0, 4.0, 6.0]
        assert "FULL_3D_STATE" not in combined


def test_combine_deletes_each_native_hour_after_compaction(monkeypatch, tmp_path):
    source_path = tmp_path / "native.nc"
    xr.Dataset(
        {
            "U10": (("Time", "south_north", "west_east"), np.ones((1, 1, 1))),
            "V10": (("Time", "south_north", "west_east"), np.zeros((1, 1, 1))),
            "XLAT": (("Time", "south_north", "west_east"), np.array([[[39.0]]])),
            "XLONG": (("Time", "south_north", "west_east"), np.array([[[2.0]]])),
        }
    ).to_netcdf(source_path)
    observed_native_paths = []

    class Blob:
        name = "wrfout_d02_2026-07-16_00:00:00"

        def download_to_filename(self, destination):
            path = Path(destination)
            path.write_bytes(source_path.read_bytes())
            observed_native_paths.append(path)

    output = tmp_path / "compact.nc"
    assert wrf_forecast_ingestor.download_and_combine_wrf_domain([Blob()], output) == 1
    assert output.exists()
    assert observed_native_paths
    assert all(not path.exists() for path in observed_native_paths)
