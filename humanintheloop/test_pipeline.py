"""Tests for the multi-tier ETL pipeline orchestrator."""

import json
from pathlib import Path
from unittest.mock import patch

import pipeline
import ingest_atmosphere


def test_pipeline_generates_run_id():
    run_id = pipeline._generate_run_id()
    assert run_id.endswith("Z")
    assert "T" in run_id


def test_step_atmospheric_skipped():
    result = pipeline._step_atmospheric("/tmp", dry_run=True, skip=True)
    assert result["wind_result"]["available"] is False
    assert result["wind_lineage"]["status"] == "skipped"


def test_step_atmospheric_dry_run_uses_ecmwf(monkeypatch, tmp_path):
    monkeypatch.delenv("METEO_FRANCE_API_KEY", raising=False)
    monkeypatch.delenv("AEMET_API_KEY", raising=False)
    result = pipeline._step_atmospheric(str(tmp_path), dry_run=True, skip=False)
    assert result["wind_result"]["available"] is True
    assert result["wind_result"]["source"] == "ecmwf_open_data"


def test_step_observations_dry_run(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", raising=False)
    result = pipeline._step_observations(dry_run=True, skip_puertos=True)
    assert "observations" in result
    assert "ground_truth_lineage" in result


def test_step_build_snapshot_attaches_lineage():
    import route_analysis

    route = route_analysis.load_route("ibiza_palma")
    atmo_result = {
        "wind_result": {"available": True, "source": "ecmwf_open_data"},
        "wind_lineage": {"source": "ecmwf_open_data", "resolution_km": 9.0, "status": "active", "tier": 3},
    }
    ocean_result = {
        "available": True,
        "forecast": route_analysis.default_forecast_summary(),
        "lineage": {"source": "copernicus_med", "resolution_km": 4.0, "status": "active"},
    }
    obs_result = {
        "observations": {},
        "ground_truth_lineage": {"source": None, "status": "unavailable"},
    }
    blend_result = {"blended": False}

    snapshot = pipeline._step_build_snapshot(
        route, "medium", ocean_result, obs_result, atmo_result, blend_result,
    )

    assert "data_lineage" in snapshot
    assert snapshot["data_lineage"]["wind_forecast"]["source"] == "ecmwf_open_data"
    assert snapshot["data_lineage"]["ocean_forecast"]["source"] == "copernicus_med"


def test_step_build_snapshot_attaches_portus_lineage():
    import route_analysis

    route = route_analysis.load_route("ibiza_palma")
    atmo_result = {
        "wind_result": {"available": True, "source": "ecmwf_open_data"},
        "wind_lineage": {"source": "ecmwf_open_data", "resolution_km": 9.0, "status": "active", "tier": 3},
    }
    ocean_result = {
        "available": True,
        "forecast": route_analysis.default_forecast_summary(),
        "lineage": {"source": "copernicus_med", "resolution_km": 4.0, "status": "active"},
    }
    obs_result = {
        "observations": {},
        "ground_truth_lineage": {"source": None, "status": "unavailable"},
        "portus": {
            "observations_lineage": {"source": "puertos_portus", "status": "matched_successfully"},
            "predictions_lineage": {"source": "puertos_portus_predictions", "status": "matched_successfully"},
        },
    }
    blend_result = {"blended": False}

    snapshot = pipeline._step_build_snapshot(
        route, "medium", ocean_result, obs_result, atmo_result, blend_result,
    )

    assert snapshot["data_lineage"]["portus_observations"]["source"] == "puertos_portus"
    assert snapshot["data_lineage"]["portus_predictions"]["source"] == "puertos_portus_predictions"
    assert snapshot["portus"]["observations_lineage"]["source"] == "puertos_portus"


def test_evidence_package_preserves_pipeline_lineage():
    import evidence_package
    import route_analysis

    route = route_analysis.load_route("ibiza_palma")
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": "ibiza_palma",
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "created_at_utc": "2026-06-08 10:00 UTC",
        "observations": {},
        "forecast": {"wave_max_m": 1.0, "wave_peak_time": "14:00"},
        "recommendation": {"best_window": "morning", "watch_out": "builds", "confidence": "medium"},
        "data_lineage": {
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
                "source": "puertos_observations",
                "status": "matched_successfully",
            },
        },
    }

    package = evidence_package.build_route_evidence_package(snapshot, route)
    assert package["data_lineage"]["wind_forecast"]["source"] == "meteo_france_arome"
    assert package["data_lineage"]["ocean_forecast"]["status"] == "interpolated_to_1.3km"
    assert package["data_lineage"]["ground_truth_validation"]["source"] == "puertos_observations"
