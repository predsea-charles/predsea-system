"""
Tests for the /observations/stations endpoint and its pure aggregation helper.

api.app.build_observation_stations_response() is a pure function (no BigQuery I/O),
so most tests here feed it hand-built rows -- the same shape client.query(...).result()
rows have (dict-like objects with .get()) -- to verify the grouping/aggregation logic
without needing real GCP credentials.

Consistent with everything else fixed in the July 2 real-validation pass: this must
never invent an observation. A station with no matching row for a variable in the
lookback window should simply be missing that variable from `observations`, not filled
with a default or a zero.
"""
from datetime import datetime, timezone

import pytest

from api.app import build_observation_stations_response, create_app
from api.evidence_store import EvidenceStore


def test_groups_multiple_variables_under_one_station():
    rows = [
        {
            "station_id": "palma_buoy",
            "station_name": "Palma Bay Buoy",
            "station_kind": "buoy",
            "network": "puertos_del_estado",
            "provider": "puertos_del_estado",
            "latitude": 39.48,
            "longitude": 2.62,
            "variable": "wave_height",
            "value": 0.6,
            "units": "m",
            "observed_at_utc": datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
        },
        {
            "station_id": "palma_buoy",
            "station_name": "Palma Bay Buoy",
            "station_kind": "buoy",
            "network": "puertos_del_estado",
            "provider": "puertos_del_estado",
            "latitude": 39.48,
            "longitude": 2.62,
            "variable": "current_speed",
            "value": 0.3,
            "units": "m/s",
            "observed_at_utc": datetime(2026, 7, 2, 10, 5, tzinfo=timezone.utc),
        },
    ]
    result = build_observation_stations_response(rows, lookback_days=3)
    assert result["status"] == "real"
    assert len(result["stations"]) == 1
    station = result["stations"][0]
    assert station["station_id"] == "palma_buoy"
    assert station["station_kind"] == "buoy"
    assert set(station["observations"].keys()) == {"wave_height", "current_speed"}
    assert station["observations"]["wave_height"]["value"] == 0.6
    assert station["observations"]["wave_height"]["observed_at_utc"] == "2026-07-02T10:00:00+00:00"


def test_keeps_different_station_kinds_separate():
    rows = [
        {"station_id": "a", "station_kind": "buoy", "latitude": 39.0, "longitude": 2.0, "variable": None, "value": None},
        {"station_id": "b", "station_kind": "tide_gauge", "latitude": 39.1, "longitude": 2.1, "variable": None, "value": None},
        {"station_id": "c", "station_kind": "radar", "latitude": 39.2, "longitude": 2.2, "variable": None, "value": None},
        {"station_id": "d", "station_kind": "platform", "latitude": 39.3, "longitude": 2.3, "variable": None, "value": None},
    ]
    result = build_observation_stations_response(rows, lookback_days=3)
    kinds = {s["station_kind"] for s in result["stations"]}
    assert kinds == {"buoy", "tide_gauge", "radar", "platform"}


def test_station_with_no_real_observation_has_empty_observations_not_a_guess():
    # This is the "LEFT JOIN found nothing" case -- station metadata exists (from
    # station_metadata rows) but no matching observation row landed in the lookback
    # window. Must not be silently dropped, and must not get a fabricated value.
    rows = [
        {
            "station_id": "quiet_buoy",
            "station_name": "Quiet Buoy",
            "station_kind": "buoy",
            "latitude": 40.0,
            "longitude": 3.0,
            "variable": None,
            "value": None,
            "units": None,
            "observed_at_utc": None,
        }
    ]
    result = build_observation_stations_response(rows, lookback_days=3, variable_filter="wave_height")
    assert len(result["stations"]) == 1
    assert result["stations"][0]["observations"] == {}
    assert result["variable_filter"] == "wave_height"


def test_rows_missing_station_id_are_skipped():
    rows = [{"station_id": None, "variable": "wave_height", "value": 1.0}]
    result = build_observation_stations_response(rows, lookback_days=3)
    assert result["stations"] == []


def test_api_endpoint_returns_503_when_bigquery_unavailable(tmp_path, monkeypatch):
    # In this sandbox/CI there's no real BigQuery config, so resolve_config() should
    # return None (per bigquery_export.resolve_config's own contract) and the endpoint
    # must fail loudly with 503, not return an empty or fabricated 200.
    monkeypatch.delenv("PREDSEA_BIGQUERY_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("PREDSEA_BIGQUERY_DATASET", raising=False)
    monkeypatch.delenv("PREDSEA_BIGQUERY_TABLE", raising=False)

    from fastapi.testclient import TestClient

    store = EvidenceStore(tmp_path)
    app = create_app(store)
    client = TestClient(app)

    response = client.get("/observations/stations")
    assert response.status_code == 503


if __name__ == "__main__":
    import sys
    raise SystemExit(pytest.main([__file__, "-v"]))
