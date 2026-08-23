import json
from pathlib import Path

import briefing
import evidence_package
from api.evidence_store import EvidenceStore


def sample_snapshot():
    return {
        "route": "Palma -> Ibiza",
        "route_id": "ibiza_palma",
        "route_note": "Exposed SW Mallorca to Ibiza crossing.",
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "created_at_utc": "2026-05-31 06:30 UTC",
        "observations": {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-05-31 06:20 UTC",
                "wave_height_m": 0.4,
            }
        },
        "forecast": {
            "wave_min_m": 0.2,
            "wave_max_m": 0.8,
            "wave_peak_time": "17:00",
            "wave_peak_direction_deg": 90.0,
            "route_bearing_deg": 240.0,
            "wave_peak_sea_state": "stern quartering sea",
            "wave_peak_relative_angle_deg": 150.0,
            "swell_1_height_m": 0.5,
            "swell_1_direction_deg": 85.0,
            "swell_2_height_m": 0.2,
            "swell_2_direction_deg": 230.0,
            "wind_wave_height_m": 0.4,
            "wind_wave_direction_deg": 100.0,
            "current_max_kn": 0.6,
            "current_peak_time": "16:00",
            "hourly": [
                {"time": "09:00", "wave_m": 0.3, "current_kn": 0.2, "wave_sea_state": "beam sea"},
                {
                    "time": "17:00",
                    "wave_m": 0.8,
                    "wave_direction_deg": 90.0,
                    "current_kn": 0.6,
                    "wave_sea_state": "stern quartering sea",
                    "swell_1_height_m": 0.5,
                    "swell_1_direction_deg": 85.0,
                    "wind_wave_height_m": 0.4,
                    "wind_wave_direction_deg": 100.0,
                },
            ],
            "sampling_method": "route_exposed_max",
            "route_segments": {
                "departure_conditions": {"name": "Palma Bay offshore", "max_wave_m": 0.5, "peak_time": "17:00"},
                "open_water_conditions": {"name": "Ibiza Channel", "max_wave_m": 0.8, "peak_time": "17:00"},
                "arrival_conditions": {"name": "Ibiza Channel", "max_wave_m": 0.8, "peak_time": "17:00"},
                "worst_segment": {
                    "id": "open_water_conditions",
                    "name": "Ibiza Channel",
                    "max_wave_m": 0.8,
                    "peak_time": "17:00",
                },
                "best_departure_window": {"time": "09:00", "wave_m": 0.3},
            },
        },
        "recommendation": {
            "best_window": "before late afternoon",
            "watch_out": "waves build toward 0.8 m around 17:00",
            "confidence": "medium",
            "vessel_severity": "manageable",
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }


def sample_route():
    return {
        "id": "ibiza_palma",
        "name": "Palma -> Ibiza",
        "route_note": "Exposed SW Mallorca to Ibiza crossing.",
        "origin": {"name": "Palma", "longitude": 2.6502, "latitude": 39.5696},
        "destination": {"name": "Ibiza", "longitude": 1.435, "latitude": 38.9089},
        "validation": {
            "truth_source": "canal_de_ibiza",
            "suitability": "representative for Ibiza Channel exposure",
        },
        "current_validation": {
            "truth_source": None,
            "suitability": "no route-specific SOCIB current observation configured",
        },
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }


def test_build_route_evidence_package_has_decision_ready_structure():
    package = evidence_package.build_route_evidence_package(sample_snapshot(), sample_route())

    assert package["schema_version"] == "predsea.evidence.v1"
    assert package["evidence_package_id"] == "ibiza_palma_20260531T063000Z"
    assert package["data_lineage"] == {
        "wind_forecast": {
            "source": None,
            "resolution_km": None,
            "status": "not_configured",
        },
        "ocean_forecast": {
            "source": "copernicus_med",
            "resolution_km": 4.0,
            "status": "active",
        },
        "ground_truth_validation": {
            "source": "puertos_observations",
            "status": "matched_successfully",
        },
    }
    assert package["subject"] == {
        "type": "route",
        "id": "ibiza_palma",
        "name": "Palma -> Ibiza",
        "note": "Exposed SW Mallorca to Ibiza crossing.",
        "origin": {"name": "Palma", "longitude": 2.6502, "latitude": 39.5696},
        "destination": {"name": "Ibiza", "longitude": 1.435, "latitude": 38.9089},
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }
    assert package["forecast"]["variables"]["wave_height_m"]["max"] == 0.8
    assert package["forecast"]["route_segments"]["worst_segment"]["name"] == "Ibiza Channel"
    assert package["forecast"]["variables"]["wave_height_m"]["peak_sea_state"] == "stern quartering sea"
    assert package["forecast"]["variables"]["swell_1"]["height_m"] == 0.5
    assert package["forecast"]["variables"]["wind_wave"]["direction_deg"] == 100.0
    assert package["forecast"]["variables"]["current_speed_kn"]["peak_time"] == "16:00"
    assert package["operational_interpretation"]["best_window"] == "before late afternoon"
    assert package["data_quality"]["nearest_wave_truth_source"] == "canal_de_ibiza"
    assert package["decision_context"] == sample_snapshot()


def test_build_route_evidence_package_preserves_existing_lineage():
    snapshot = sample_snapshot()
    snapshot["evidence_package_id"] = "custom_run_id"
    snapshot["data_lineage"] = {
        "wind_forecast": {
            "source": "meteo_france_arome",
            "resolution_km": 1.3,
            "status": "blended",
        },
        "ocean_forecast": {
            "source": "copernicus_med",
            "resolution_km": 4.0,
            "status": "interpolated_to_1.3km",
        },
        "ground_truth_validation": {
            "source": "puertos_del_estado",
            "status": "matched_successfully",
        },
    }

    package = evidence_package.build_route_evidence_package(snapshot, sample_route())

    assert package["evidence_package_id"] == "custom_run_id"
    assert package["data_lineage"] == snapshot["data_lineage"]


def test_write_outputs_writes_evidence_json_beside_daily_snapshot(tmp_path):
    snapshot = sample_snapshot()
    briefing.write_outputs(snapshot, output_dir=tmp_path, route=sample_route())

    evidence_path = tmp_path / "evidence.json"

    assert evidence_path.exists()
    package = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert package["subject"]["id"] == "ibiza_palma"
    assert package["decision_context"]["forecast"]["wave_max_m"] == 0.8


def test_evidence_store_prefers_evidence_decision_context_over_daily_snapshot(tmp_path):
    route_dir = Path(tmp_path) / "2026-05-31" / "ibiza_palma"
    route_dir.mkdir(parents=True)
    (route_dir / "daily_snapshot.json").write_text(
        json.dumps({"route_id": "ibiza_palma", "forecast": {"wave_max_m": 9.9}}),
        encoding="utf-8",
    )
    (route_dir / "evidence.json").write_text(
        json.dumps(
            {
                "schema_version": "predsea.evidence.v1",
                "decision_context": {
                    "route_id": "ibiza_palma",
                    "forecast": {"wave_max_m": 0.8},
                },
            }
        ),
        encoding="utf-8",
    )

    snapshot = EvidenceStore(tmp_path).load_snapshot("ibiza_palma", "2026-05-31")

    assert snapshot["forecast"]["wave_max_m"] == 0.8
