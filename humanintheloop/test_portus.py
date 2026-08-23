"""Tests for Portus ETL helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import fetch_portus
import portus_observations
import portus_parsers
import portus_predictions


def test_parse_station_data_preserves_qc_and_missing_values():
    payload = [
        ["UTC", "Hm0 (m)", "Wind speed (m/s)", "Current speed (m/s)", "Temperature (°C)"],
        [
            [1779408000, [0.2, 1], [3.1, 0], [0.6, 1], [21.4, 2]],
            [1779411600, [0.4, 1], [3.5, 0], [-9999.9, 9], [21.8, 2]],
        ],
    ]

    frame = portus_parsers.parse_station_data(payload, "3545")

    assert list(frame["station_code"].unique()) == ["3545"]
    assert "hs_m" in frame.columns
    assert "wind_speed_mps" in frame.columns
    assert "current_speed_mps" in frame.columns
    assert "temperature_c" in frame.columns
    assert "hs_m_qc" in frame.columns
    assert pd.isna(frame.loc[1, "current_speed_mps"])
    assert frame.loc[0, "wind_speed_mps_qc"] == 0
    assert str(frame.loc[0, "time_utc"].tzinfo) == "UTC"


def test_parse_model_points_normalizes_metadata():
    payload = [
        {
            "longitud": -5.42,
            "latitud": 36.07,
            "id": 9000002,
            "modelo": "portus",
            "tipo": 5,
            "codigoEstacion": 1504,
            "region": "Med",
            "tdelta": 1,
            "tunidad": "HOR",
        }
    ]

    frame = portus_parsers.parse_model_points(payload)

    assert frame.loc[0, "model_point_id"] == 9000002
    assert frame.loc[0, "model_name"] == "portus"
    assert frame.loc[0, "station_code_for_verification"] == 1504
    assert frame.loc[0, "time_step"] == 1
    assert frame.loc[0, "time_unit"] == "HOR"


def test_parse_last_positions_wraps_dict_payload():
    payload = {"time": "2026-06-11T00:00:00Z", "hs_m": 0.5}

    frame = portus_parsers.parse_last_positions(payload, 9000002, station_code_for_verification=1504)

    assert frame.loc[0, "model_point_id"] == 9000002
    assert frame.loc[0, "station_code_for_verification"] == 1504
    assert frame.loc[0, "hs_m"] == 0.5


def test_fetch_portus_observations_dry_run_uses_configured_station():
    result = portus_observations.fetch_portus_observations(dry_run=True)

    assert "portus_3545" in result["observations"]
    assert result["lineage"]["source"] == "puertos_portus"
    assert result["lineage"]["status"] == "matched_successfully"


def test_fetch_portus_bundle_dry_run():
    result = fetch_portus.fetch_portus_bundle(dry_run=True)

    assert result["source"] == "puertos_portus"
    assert result["available"] is True
    assert "observations" in result
    assert "predictions" in result


def test_fetch_latest_position_parses_monkeypatched_response(monkeypatch):
    def fake_fetch_json(url, **kwargs):
        assert "lastData/positions/9000002" in url
        return {"time": "2026-06-11T00:00:00Z", "hs_m": 0.5}

    monkeypatch.setattr(portus_predictions.portus_client, "fetch_json", fake_fetch_json)

    result = portus_predictions.fetch_latest_position(9000002, station_code_for_verification=1504)

    assert result["available"] is True
    assert result["row_count"] == 1
    assert result["records"][0]["hs_m"] == 0.5


def test_fetch_portus_predictions_dry_run():
    result = portus_predictions.fetch_portus_predictions(dry_run=True)

    assert result["source"] == "puertos_portus"
    assert result["dry_run"] is True


def test_fetch_portus_predictions_skips_empty_latest_positions(monkeypatch):
    def fake_discover_model_points(**kwargs):
        return {
            "available": True,
            "source": "puertos_portus",
            "model_name": "Cirana",
            "row_count": 1,
            "dataframe": pd.DataFrame(
                [
                    {
                        "model_point_id": 9000002,
                        "station_code_for_verification": 1504,
                    }
                ]
            ),
            "records": [
                {
                    "model_point_id": 9000002,
                    "station_code_for_verification": 1504,
                }
            ],
        }

    called = {"latest": 0}

    def fake_fetch_latest_position(*args, **kwargs):
        called["latest"] += 1
        return {"available": True, "records": []}

    monkeypatch.setattr(portus_predictions, "discover_model_points", fake_discover_model_points)
    monkeypatch.setattr(portus_predictions, "fetch_latest_position", fake_fetch_latest_position)

    result = portus_predictions.fetch_portus_predictions()

    assert result["available"] is True
    assert called["latest"] == 0
    assert result["lineage"]["latest_positions_enabled"] is False
