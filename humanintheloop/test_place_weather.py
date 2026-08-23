import json
from pathlib import Path

import pytest

from place_registry import (
    default_place_id_for_query,
    place_pair_metrics,
    resolve_place_query,
    station_candidates_for_place,
)
from place_weather import (
    available_place_ids,
    build_place_weather_record,
    place_definition,
    place_connection_metrics,
    select_observation_for_place,
)


def test_build_place_weather_record_uses_place_weather_fields():
    forecast = {
        "wave_min_m": 0.3,
        "wave_max_m": 0.8,
        "wave_peak_time": "08:00",
        "wave_peak_direction_deg": 72.0,
        "current_max_kn": 0.4,
        "current_peak_time": "10:00",
        "hourly": [
            {
                "time": "08:00",
                "time_utc": "2026-06-12 06:00 UTC",
                "wave_m": 0.8,
                "wave_direction_deg": 72.0,
                "wave_sea_state": "beam sea",
                "current_kn": 0.4,
                "swell_1_height_m": 0.5,
                "swell_1_direction_deg": 68.0,
                "swell_2_height_m": 0.2,
                "swell_2_direction_deg": 84.0,
                "wind_wave_height_m": 0.3,
                "wind_wave_direction_deg": 80.0,
            },
            {
                "time": "10:00",
                "time_utc": "2026-06-12 08:00 UTC",
                "wave_m": 0.6,
                "wave_direction_deg": 76.0,
                "current_kn": 0.2,
            },
        ],
    }
    observation = {
        "station_id": "canal_de_ibiza",
        "station_name": "Buoy Canal de Ibiza",
        "observed_at_utc": "2026-06-12 07:30 UTC",
        "wave_height_m": 0.4,
        "wave_from_direction_deg": 82.0,
        "wind_kn": 12.0,
        "wind_gust_kn": 18.0,
        "wind_direction_deg": 70.0,
        "water_temperature_c": 22.4,
        "temperature_c": 23.1,
    }

    record = build_place_weather_record(
        "ibiza",
        forecast,
        observation=observation,
        generated_at_utc="2026-06-12 08:00 UTC",
        run_date="2026-06-12",
        run_id="2026-06-12T0750Z",
    )

    assert record["place_id"] == "ibiza"
    assert record["place_name"] == "Ibiza"
    assert record["date"] == "2026-06-12"
    assert record["run"] == "2026-06-12T0750Z"
    assert record["wave_height_m"] == 0.8
    assert record["wave_direction_deg"] == 72.0
    assert record["swell_1_height_m"] == 0.5
    assert record["swell_2_height_m"] == 0.2
    assert record["wind_kn"] == 12.0
    assert record["wind_gust_kn"] == 18.0
    assert record["water_temperature_c"] == 22.4
    assert record["air_temperature_c"] == 23.1
    assert record["freshness_status"] == "fresh"
    assert record["freshness_state"] == "LIVE"
    assert record["observation"]["station_name"] == "Buoy Canal de Ibiza"
    assert record["hourly"][0]["time"] == "08:00"


def test_build_place_weather_record_converts_wind_speed_mps_to_knots():
    forecast = {
        "wave_min_m": 0.2,
        "wave_max_m": 0.4,
        "wave_peak_time": "08:00",
        "wave_peak_direction_deg": 40.0,
        "current_max_kn": 0.1,
        "hourly": [],
    }
    observation = {
        "station_id": "alcudia",
        "station_name": "Alcudia",
        "observed_at_utc": "2026-06-12 07:30 UTC",
        "wind_speed_mps": 5.0,
        "wind_gust": 8.0,
        "wind_direction_deg": 110.0,
    }
    record = build_place_weather_record(
        "alcudia",
        forecast,
        observation=observation,
        generated_at_utc="2026-06-12 08:00 UTC",
        run_date="2026-06-12",
        run_id="2026-06-12T0750Z",
    )
    assert record["wind_direction_deg"] == 110.0
    assert record["wind_kn"] == pytest.approx(5.0 * 1.94384)
    assert record["wind_gust_kn"] == pytest.approx(8.0 * 1.94384)


def test_available_place_ids_include_new_locations():
    place_ids = available_place_ids()
    assert "ciutadella" in place_ids
    assert "alcudia" in place_ids
    assert "soller" in place_ids
    assert "portocolom" in place_ids
    assert "port_de_palma" in place_ids
    assert "port_adriano" in place_ids
    assert "can_pastilla" in place_ids
    assert {"san_antonio", "andratx", "fornells", "addaia", "tarragona", "palamos"}.issubset(set(place_ids))


def test_cala_fornells_is_in_mallorca_and_routes_use_its_real_coordinates():
    fornells = place_definition("fornells")

    assert fornells["name"] == "Cala Fornells"
    assert fornells["latitude"] == pytest.approx(39.5333)
    assert fornells["longitude"] == pytest.approx(2.4379)
    assert fornells["parent_place_id"] == "palma"
    assert "mallorca" in fornells["observation_candidates"]
    assert "menorca" not in fornells["observation_candidates"]

    routes_path = Path(__file__).with_name("routes.json")
    routes = json.loads(routes_path.read_text(encoding="utf-8"))
    fornells_routes = [
        route
        for route in routes.values()
        if route["destination"]["name"] == "Cala Fornells"
    ]

    assert fornells_routes
    for route in fornells_routes:
        assert route["destination"]["latitude"] == pytest.approx(39.5333)
        assert route["destination"]["longitude"] == pytest.approx(2.4379)
        assert route["sample_points"][-1]["latitude"] == pytest.approx(39.5333)
        assert route["sample_points"][-1]["longitude"] == pytest.approx(2.4379)


def test_palma_defaults_to_main_place_and_has_children():
    assert default_place_id_for_query("Palma") == "palma"
    assert default_place_id_for_query("Port de Palma") == "port_de_palma"

    palma = place_definition("palma")
    child_ids = list(palma["children"])
    assert palma["parent_place_id"] is None
    assert palma["kind"] == "main_port"
    assert "port_de_palma" in child_ids
    assert "port_adriano" in child_ids
    assert "can_pastilla" in child_ids


def test_place_resolution_does_not_recurse_between_catalog_and_query_lookup():
    resolved = resolve_place_query("Port de Palma")

    assert resolved["matched"] is True
    assert resolved["place_id"] == "port_de_palma"
    assert resolved["place_name"] == "Port de Palma"
    assert default_place_id_for_query("unknown place") is None


def test_place_pair_metrics_are_precomputed_and_accessible_from_place_weather():
    metrics = place_pair_metrics("palma", "portocolom")
    connection = place_connection_metrics("palma", "portocolom")

    assert metrics["origin_place_id"] == "palma"
    assert metrics["destination_place_id"] == "portocolom"
    assert metrics["distance_nm"] > 0
    assert metrics["typical_travel_time_minutes"] > 0
    assert connection["distance_nm"] == metrics["distance_nm"]
    assert connection["typical_travel_time_minutes"] == metrics["typical_travel_time_minutes"]


def test_station_candidates_are_explicit_and_ordered_for_portocolom():
    candidates = station_candidates_for_place("portocolom")
    assert candidates[:2] == ("porto_colom", "puertos_mallorca")


def test_portocolom_is_supported_and_prefers_its_observation_key():
    place = place_definition("portocolom")
    assert place["name"] == "Portocolom"
    assert place["parent_place_id"] == "palma"
    assert place["observation_candidates"][0] == "porto_colom"
    assert "puertos_mallorca" in place["observation_candidates"]

    observation = {
        "station_id": "porto_colom",
        "station_name": "Portocolom",
        "wave_height_m": 0.7,
    }
    selected = select_observation_for_place("portocolom", {"porto_colom": observation})
    assert selected["station_id"] == "porto_colom"
    assert selected["station_name"] == "Portocolom"


def test_portocolom_falls_back_to_nearest_balearic_observation():
    selected = select_observation_for_place(
        "portocolom",
        {
            "alcudia": {
                "station_id": "alcudia",
                "station_name": "Alcudia",
                "wave_height_m": 0.6,
            }
        },
    )
    assert selected["station_id"] == "alcudia"
    assert selected["station_name"] == "Alcudia"


def test_build_place_weather_record_accepts_naive_observation_timestamp():
    forecast = {
        "wave_min_m": 0.2,
        "wave_max_m": 0.4,
        "wave_peak_time": "08:00",
        "wave_peak_direction_deg": 40.0,
        "current_max_kn": 0.1,
        "hourly": [],
    }
    observation = {
        "station_id": "alcudia",
        "station_name": "Alcudia",
        "observed_at_utc": "2026-06-12 07:30",
        "wave_height_m": 0.3,
    }
    record = build_place_weather_record(
        "alcudia",
        forecast,
        observation=observation,
        generated_at_utc="2026-06-12 08:00 UTC",
        run_date="2026-06-12",
        run_id="2026-06-12T0750Z",
    )
    assert record["freshness_status"] == "fresh"
    assert record["freshness_state"] == "LIVE"
    assert record["metadata"]["observation_age_minutes"] == 30


def test_build_place_weather_record_keeps_future_observation_timestamp():
    forecast = {
        "wave_min_m": 0.2,
        "wave_max_m": 0.4,
        "wave_peak_time": "08:00",
        "wave_peak_direction_deg": 40.0,
        "current_max_kn": 0.1,
        "hourly": [],
    }
    observation = {
        "station_id": "alcudia",
        "station_name": "Alcudia",
        "last_sample_utc": "2026-06-18 07:30 UTC",
        "wave_height_m": 0.3,
    }
    record = build_place_weather_record(
        "alcudia",
        forecast,
        observation=observation,
        generated_at_utc="2026-06-15 08:00 UTC",
        run_date="2026-06-15",
        run_id="2026-06-15T0750Z",
    )
    assert record["freshness_status"] == "unknown"
    assert record["freshness_state"] == "FUTURE"
    assert record["metadata"]["observation_age_minutes"] is None
    assert record.get("observed_at_utc") == "2026-06-18 07:30 UTC"
    assert record.get("source_time_coordinate_utc") == "2026-06-18 07:30 UTC"
    assert record["observation"]["is_future"] is True
