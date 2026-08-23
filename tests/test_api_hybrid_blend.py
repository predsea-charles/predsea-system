#!/usr/bin/env python3
"""
Tests for FastAPI Hybrid Blending in app.py.
"""
from __future__ import annotations

import datetime
import math
import sys
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

# Add humanintheloop directory to path so we can import api.app
HUMANINTHELOOP_DIR = Path(__file__).resolve().parents[1] / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

from api.app import blend_hourly_forecasts, parse_utc_timestamp_lenient


class DummyStore:
    def resolve_date(self, val):
        return "2026-06-24"


@pytest.fixture
def dummy_store():
    return DummyStore()


def test_blend_hourly_forecasts_basic_and_truncation(dummy_store):
    # Setup some dummy hourly list with elements up to 130 hours
    T_0 = datetime.datetime(2026, 6, 24, 0, 0, tzinfo=datetime.timezone.utc)
    hourly_list = []
    for h in range(125):
        t_utc = T_0 + datetime.timedelta(hours=h)
        hourly_list.append({
            "time": t_utc.strftime("%H:%M"),
            "time_utc": t_utc.strftime("%Y-%m-%d %H:%M UTC"),
            "wave_m": 0.5,
            "wave_direction_deg": 120.0,
            "wave_sea_state": "smooth",
            "swell_1_height_m": 0.3,
            "swell_1_direction_deg": 120.0,
            "swell_2_height_m": 0.1,
            "swell_2_direction_deg": 120.0,
            "wind_wave_height_m": 0.2,
            "wind_wave_direction_deg": 120.0,
            "current_kn": 0.2,
            "current_direction_deg": 180.0,
            "wind_kn": 10.0,
            "wind_direction_deg": 90.0,
            "air_temperature_c": 22.0,
            "water_temperature_c": 19.5,
            "sea_level_pressure_hpa": 1013.25,
        })

    # Test that hours > 120 are truncated, and hours 126 to 240 (at 6h intervals, so 20 items) are appended.
    # Total count should be 121 (for hours 0 to 120) + 20 (hours 126 to 240) = 141.
    blended = blend_hourly_forecasts(dummy_store, hourly_list, run_date="2026-06-24")
    
    assert len(blended) == 141
    
    # Assert hours 0-120 remain
    for i in range(121):
        item_time = parse_utc_timestamp_lenient(blended[i]["time_utc"])
        lead_h = (item_time - T_0).total_seconds() / 3600.0
        assert lead_h == float(i)

    # Assert hours after 120 are appended at 6h intervals (126, 132, ..., 240)
    expected_appended_hours = list(range(126, 241, 6))
    assert len(expected_appended_hours) == 20
    
    for idx, expected_h in enumerate(expected_appended_hours):
        item = blended[121 + idx]
        item_time = parse_utc_timestamp_lenient(item["time_utc"])
        lead_h = (item_time - T_0).total_seconds() / 3600.0
        assert lead_h == float(expected_h)
        assert item["source"] == "copernicus_marine"
        assert item["source_system"] == "copernicus"


@patch("google.cloud.bigquery.Client")
def test_blend_hourly_forecasts_with_bigquery_fallback(mock_bq_client_class, dummy_store):
    # Setup BigQuery query failure (should trigger fallback/generator)
    mock_bq_client_class.side_effect = Exception("BigQuery connection error")
    
    T_0 = datetime.datetime(2026, 6, 24, 0, 0, tzinfo=datetime.timezone.utc)
    hourly_list = [{
        "time_utc": T_0.strftime("%Y-%m-%d %H:%M UTC"),
        "wave_m": 1.0,
        "wave_direction_deg": 180.0,
        "current_kn": 0.5,
        "current_direction_deg": 200.0,
        "wind_kn": 12.0,
        "wind_direction_deg": 270.0,
    }]
    
    blended = blend_hourly_forecasts(dummy_store, hourly_list, run_date="2026-06-24")
    
    # Total count = 1 input hour + 20 appended hours = 21 items
    assert len(blended) == 21
    
    # Verifying that the appended hours have computed values using the fallback generator
    appended_item = blended[1]
    assert appended_item["wave_m"] is not None
    assert appended_item["wave_direction_deg"] == 180.0
    assert appended_item["current_kn"] is not None
    assert appended_item["current_direction_deg"] == 200.0
    assert appended_item["wind_kn"] is not None
    assert appended_item["wind_direction_deg"] == 270.0


@patch("google.cloud.bigquery.Client")
def test_blend_hourly_forecasts_with_bigquery_success(mock_bq_client_class, dummy_store):
    # Mock BigQuery to return custom forecast data for Copernicus
    mock_client = MagicMock()
    mock_bq_client_class.return_value = mock_client
    
    T_0 = datetime.datetime(2026, 6, 24, 0, 0, tzinfo=datetime.timezone.utc)
    
    # Target time: 126 hours later
    target_time_126 = T_0 + datetime.timedelta(hours=126)
    
    # Mock rows returned by BigQuery query
    mock_row_1 = {"variable": "wave_height", "target_time_utc": target_time_126.strftime("%Y-%m-%d %H:%M:%S"), "value": 2.5}
    mock_row_2 = {"variable": "wave_direction", "target_time_utc": target_time_126.strftime("%Y-%m-%d %H:%M:%S"), "value": 45.0}
    mock_row_3 = {"variable": "current_speed", "target_time_utc": target_time_126.strftime("%Y-%m-%d %H:%M:%S"), "value": 0.3} # 0.3 m/s * 1.94384 knots/ms = 0.58 knots
    mock_row_4 = {"variable": "current_direction", "target_time_utc": target_time_126.strftime("%Y-%m-%d %H:%M:%S"), "value": 15.0}
    
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [mock_row_1, mock_row_2, mock_row_3, mock_row_4]
    mock_client.query.return_value = mock_query_job
    
    hourly_list = [{
        "time_utc": T_0.strftime("%Y-%m-%d %H:%M UTC"),
        "wave_m": 1.0,
        "wave_direction_deg": 180.0,
        "current_kn": 0.5,
        "current_direction_deg": 200.0,
        "wind_kn": 12.0,
        "wind_direction_deg": 270.0,
    }]
    
    blended = blend_hourly_forecasts(dummy_store, hourly_list, run_date="2026-06-24", place_id="palma_harbor")
    
    assert len(blended) == 21
    
    # Check that item at hour 126 (which is index 1 of the blended output list) uses BigQuery results
    item_126 = blended[1]
    assert item_126["wave_m"] == 2.5
    assert item_126["wave_direction_deg"] == 45.0
    assert item_126["current_kn"] == round(0.3 * 1.9438444924406, 2)
    assert item_126["current_direction_deg"] == 15.0
