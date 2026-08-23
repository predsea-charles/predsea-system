import json
from pathlib import Path
from datetime import datetime, timezone

import validation_archive


def test_validation_archive_matches_observation_to_forecast(tmp_path):
    run_dir = tmp_path / "outputs" / "2026-06-09" / "runs" / "2026-06-09T1200Z"
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
            "created_at_utc": "2026-06-09 12:00 UTC",
            "forecast_source": {"id": "copernicus", "label": "Copernicus"},
            "data_lineage": {
                "ocean_forecast": {
                    "source": "copernicus_med",
                    "resolution_km": 4.0,
                }
            },
            "forecast": {
                "hourly": [
                    {
                        "time": "16:00",
                        "time_utc": "2026-06-09 16:00 UTC",
                        "wave_m": 0.9,
                        "wave_direction_deg": 25.0,
                    }
                ]
            },
        }
    }
    observations = {
        "canal_de_ibiza": {
            "name": "Buoy Canal de Ibiza",
            "last_sample_utc": "2026-06-09 16:00 UTC",
            "wave_height_m": 0.43,
        }
    }

    summary = validation_archive.write_validation_archive(
        run_dir,
        "2026-06-09",
        "2026-06-09T1200Z",
        routes,
        snapshots,
        observations,
        tmp_path / "outputs",
    )

    matched_path = run_dir / "validation" / "matched_validation.jsonl"
    matched = [json.loads(line) for line in matched_path.read_text(encoding="utf-8").splitlines()]

    assert summary["observation_rows"] == 1
    assert summary["forecast_rows"] == 2
    assert summary["matched_rows"] == 1
    assert summary["station_metadata_rows"] == 1
    assert json.loads((run_dir / "validation" / "observation_samples.jsonl").read_text(encoding="utf-8").splitlines()[0])["source_family"] == "observation"
    assert json.loads((run_dir / "validation" / "forecast_index.jsonl").read_text(encoding="utf-8").splitlines()[0])["source_family"] == "ocean_forecast"
    assert matched[0]["route_id"] == "ibiza_palma"
    assert matched[0]["truth_station_id"] == "canal_de_ibiza"
    assert matched[0]["variable"] == "wave_height"
    assert matched[0]["forecast_value"] == 0.9
    assert matched[0]["observed_value"] == 0.43
    assert matched[0]["error"] == 0.47
    assert matched[0]["absolute_error"] == 0.47
    assert matched[0]["lead_time_hours"] == 4.0


def test_validation_archive_links_new_observation_to_earlier_forecast(tmp_path):
    output_root = tmp_path / "outputs"
    old_run = output_root / "2026-06-09" / "runs" / "2026-06-09T0800Z"
    old_validation = old_run / "validation"
    old_validation.mkdir(parents=True)
    validation_archive.write_jsonl(
        old_validation / "forecast_index.jsonl",
        [
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
                "value": 0.8,
                "units": "m",
                "lead_time_hours": 8.0,
            }
        ],
    )

    new_run = output_root / "2026-06-09" / "runs" / "2026-06-09T1630Z"
    summary = validation_archive.write_validation_archive(
        new_run,
        "2026-06-09",
        "2026-06-09T1630Z",
        {},
        {},
        {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-06-09 16:00 UTC",
                "wave_height_m": 0.5,
            }
        },
        output_root,
    )

    matched = [
        json.loads(line)
        for line in (new_run / "validation" / "matched_validation.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert summary["forecast_rows"] == 0
    assert summary["matched_rows"] == 1
    assert summary["station_metadata_rows"] == 1
    assert matched[0]["forecast_run_id"] == "2026-06-09T0800Z"
    assert matched[0]["observed_value"] == 0.5
    assert matched[0]["error"] == 0.3


def test_validation_archive_keeps_future_observations(tmp_path, monkeypatch):
    run_dir = tmp_path / "outputs" / "2026-06-15" / "runs" / "2026-06-15T1200Z"
    routes = {}
    snapshots = {}
    observations = {
        "canal_de_ibiza": {
            "name": "Buoy Canal de Ibiza",
            "last_sample_utc": "2026-06-18 06:00 UTC",
            "wave_height_m": 0.43,
        }
    }
    monkeypatch.setattr(
        validation_archive,
        "current_timestamp_utc",
        lambda: datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    summary = validation_archive.write_validation_archive(
        run_dir,
        "2026-06-15",
        "2026-06-15T1200Z",
        routes,
        snapshots,
        observations,
        tmp_path / "outputs",
    )

    observation_path = run_dir / "validation" / "observation_samples.jsonl"
    station_metadata_path = run_dir / "validation" / "station_metadata.jsonl"
    assert summary["observation_rows"] == 1
    assert summary["station_metadata_rows"] == 1
    observation_rows = [
        json.loads(line)
        for line in observation_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(observation_rows) == 1
    assert observation_rows[0]["is_future"] is True
    assert observation_rows[0]["freshness_status"] == "future"
    assert observation_rows[0]["source_family"] == "observation"
    assert "station_metadata" in station_metadata_path.read_text(encoding="utf-8")


def test_validation_archive_flattens_measurements_to_long_rows(tmp_path):
    run_dir = tmp_path / "outputs" / "2026-06-15" / "runs" / "2026-06-15T1200Z"
    observations = {
        "puertos_ibiza": {
            "provider": "puertos_del_estado",
            "source_system": "puertos_del_estado",
            "source_label": "REDEXT",
            "station_name": "Ibiza",
            "dataset_url": "https://example.test/dataset.nc4",
            "measurements": [
                {
                    "station_id": "puertos_ibiza",
                    "station_name": "Ibiza",
                    "variable": "wave_height",
                    "raw_key": "wave_height_m",
                    "source_field": "VHM0",
                    "value": 0.42,
                    "units": "m",
                    "sample_time_utc": "2026-06-15T06:00:00Z",
                    "observed_at_utc": "2026-06-15T06:00:00Z",
                    "source_time_coordinate_utc": "2026-06-15T06:00:00Z",
                    "qc_flag": 1,
                    "freshness_status": "live",
                    "freshness_state": "LIVE",
                    "quality_score": 0.91,
                    "dataset_url": "https://example.test/dataset.nc4",
                },
                {
                    "station_id": "puertos_ibiza",
                    "station_name": "Ibiza",
                    "variable": "wind_speed",
                    "raw_key": "wind_speed_mps",
                    "source_field": "WSPD",
                    "value": 4.1,
                    "units": "m/s",
                    "sample_time_utc": "2026-06-15T07:00:00Z",
                    "observed_at_utc": "2026-06-15T07:00:00Z",
                    "source_time_coordinate_utc": "2026-06-15T07:00:00Z",
                    "qc_flag": 2,
                    "freshness_status": "recent",
                    "freshness_state": "RECENT",
                    "quality_score": 0.87,
                    "dataset_url": "https://example.test/dataset.nc4",
                },
            ],
        }
    }

    summary = validation_archive.write_validation_archive(
        run_dir,
        "2026-06-15",
        "2026-06-15T1200Z",
        {},
        {},
        observations,
        tmp_path / "outputs",
    )

    observation_rows = [
        json.loads(line)
        for line in (run_dir / "validation" / "observation_samples.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert summary["observation_rows"] == 2
    assert [row["variable"] for row in observation_rows] == ["wave_height", "wind_speed"]
    assert all(row["station_id"] == "puertos_ibiza" for row in observation_rows)
    assert all(row["dataset_url"] == "https://example.test/dataset.nc4" for row in observation_rows)
    assert all(row["source_family"] == "observation" for row in observation_rows)


def test_validation_archive_writes_source_inventory_rows(tmp_path):
    run_dir = tmp_path / "outputs" / "2026-06-15" / "runs" / "2026-06-15T1200Z"
    summary = validation_archive.write_validation_archive(
        run_dir,
        "2026-06-15",
        "2026-06-15T1200Z",
        {},
        {},
        {},
        tmp_path / "outputs",
        source_inventory=[
            {
                "id": "ecmwf_open_data",
                "label": "ECMWF Open Data",
                "available": True,
                "source_family": "atmosphere",
            }
        ],
    )

    source_rows = [
        json.loads(line)
        for line in (run_dir / "validation" / "source_inventory.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert summary["source_inventory_rows"] == 1
    assert source_rows[0]["record_type"] == "source_inventory"
    assert source_rows[0]["source_family"] == "atmosphere"
    assert source_rows[0]["variable"] == "source_status"
