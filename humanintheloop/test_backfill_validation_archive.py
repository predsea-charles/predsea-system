import importlib.util
import json
from pathlib import Path


def load_backfill_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_validation_archive.py"
    spec = importlib.util.spec_from_file_location("backfill_validation_archive", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_builds_archive_from_snapshots_and_history():
    backfill = load_backfill_module()
    routes = {
        "ibiza_palma": {
            "id": "ibiza_palma",
            "name": "Palma -> Ibiza",
            "validation": {"truth_source": "canal_de_ibiza"},
            "current_validation": {"truth_source": None},
        }
    }
    snapshots = {
        "ibiza_palma": {
            "route": "Palma -> Ibiza",
            "route_id": "ibiza_palma",
            "created_at_utc": "2026-06-09 16:00 UTC",
            "forecast_source": {"id": "copernicus"},
            "data_lineage": {"ocean_forecast": {"source": "copernicus_med", "resolution_km": 4.0}},
            "observations": {
                "canal_de_ibiza": {
                    "name": "Buoy Canal de Ibiza",
                    "last_sample_utc": "2026-06-09 16:00 UTC",
                    "wave_height_m": 0.43,
                }
            },
            "forecast": {
                "hourly": [
                    {
                        "time": "20:00",
                        "time_utc": "2026-06-09 20:00 UTC",
                        "wave_m": 0.8,
                    }
                ]
            },
        }
    }
    historical_rows = [
        {
            "run_id": "2026-06-09T0800Z",
            "route_id": "ibiza_palma",
            "route_name": "Palma -> Ibiza",
            "truth_station_id": "canal_de_ibiza",
            "target_time_utc": "2026-06-09T16:00:00Z",
            "forecast_created_at_utc": "2026-06-09T08:00:00Z",
            "forecast_source_id": "copernicus",
            "ocean_source": "copernicus_med",
            "resolution_km": 4.0,
            "variable": "wave_height",
            "value": 0.9,
            "units": "m",
            "lead_time_hours": 8.0,
        }
    ]

    archive = backfill.build_run_archive(
        "2026-06-09",
        "2026-06-09T1600Z",
        routes,
        snapshots,
        snapshots["ibiza_palma"]["observations"],
        historical_rows,
    )

    assert archive["summary"]["observation_rows"] == 1
    assert archive["summary"]["forecast_rows"] == 1
    assert archive["summary"]["matched_rows"] == 1
    assert archive["matched_rows"][0]["forecast_run_id"] == "2026-06-09T0800Z"
    assert archive["matched_rows"][0]["error"] == 0.47


def test_backfill_updates_manifest_payload_with_validation_entry():
    backfill = load_backfill_module()
    manifest = {"run_id": "2026-06-09T1600Z", "routes": ["ibiza_palma"]}
    entry = {
        "path": "validation/validation_summary.json",
        "matched_rows": 2,
    }

    updated = backfill.update_manifest_payload(manifest, entry)

    assert updated["validation"] == entry
    assert updated["run_id"] == "2026-06-09T1600Z"
    assert "validation" not in manifest


def test_backfill_jsonl_round_trip():
    backfill = load_backfill_module()
    rows = [{"a": 1}, {"b": "two"}]

    text = backfill.jsonl_text(rows)

    assert backfill.parse_jsonl(text) == rows
    assert json.loads(text.splitlines()[0]) == {"a": 1}


def test_backfill_threads_bigquery_settings_through_apply(monkeypatch):
    backfill = load_backfill_module()

    class FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        def list_dates(self):
            return ["2026-06-09"]

        def list_runs(self, run_date):
            return ["2026-06-09T1600Z"]

        def list_route_ids(self, run_date, run_id):
            return ["ibiza_palma"]

        def load_snapshot(self, run_date, run_id, route_id):
            return {
                "route": "Palma -> Ibiza",
                "route_id": route_id,
                "created_at_utc": "2026-06-09 16:00 UTC",
                "forecast_source": {"id": "copernicus"},
                "data_lineage": {"ocean_forecast": {"source": "copernicus_med", "resolution_km": 4.0}},
                "observations": {
                    "canal_de_ibiza": {
                        "name": "Buoy Canal de Ibiza",
                        "last_sample_utc": "2026-06-09 16:00 UTC",
                        "wave_height_m": 0.43,
                    }
                },
                "forecast": {
                    "hourly": [
                        {
                            "time": "20:00",
                            "time_utc": "2026-06-09 20:00 UTC",
                            "wave_m": 0.8,
                        }
                    ]
                },
            }

        def validation_exists(self, run_date, run_id):
            return False

        def latest_run_id(self, run_date):
            return "2026-06-09T1600Z"

        def download_json(self, *parts):
            return None

        def upload_text(self, text, *parts):
            return "/".join(parts)

        def upload_json(self, payload, *parts):
            return "/".join(parts)

    captured = {}

    def fake_load_routes():
        return {
            "ibiza_palma": {
                "id": "ibiza_palma",
                "name": "Palma -> Ibiza",
                "validation": {"truth_source": "canal_de_ibiza"},
                "current_validation": {"truth_source": None},
            }
        }

    def fake_bq_export(observation_rows, forecast_rows, **kwargs):
        captured["observation_rows"] = observation_rows
        captured["forecast_rows"] = forecast_rows
        captured["kwargs"] = kwargs
        return {"status": "written", "exported_rows": len(observation_rows) + len(forecast_rows)}

    monkeypatch.setattr(backfill, "GcsValidationBackfill", FakeStore)
    monkeypatch.setattr(backfill.route_analysis, "load_routes", fake_load_routes)
    monkeypatch.setattr(backfill.bigquery_export, "export_validation_rows_to_bigquery", fake_bq_export)

    results = backfill.backfill_validation_archives(
        apply=True,
        bigquery_project="predsea-api",
        bigquery_dataset="predsea_validation",
        bigquery_table="evidence_rows",
        bigquery_location="europe-west1",
    )

    assert results[0]["status"] == "written"
    assert captured["kwargs"]["project_id"] == "predsea-api"
    assert captured["kwargs"]["dataset_id"] == "predsea_validation"
    assert captured["kwargs"]["table_id"] == "evidence_rows"
    assert captured["kwargs"]["location"] == "europe-west1"
