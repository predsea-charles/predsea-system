import importlib.util
from pathlib import Path


def load_script_module(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_climatology_defaults_to_eu_location(monkeypatch):
    script = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "build_climatology.py")
    captured = {}

    monkeypatch.delenv("PREDSEA_BIGQUERY_LOCATION", raising=False)
    monkeypatch.delenv("BQ_LOCATION", raising=False)

    def fake_query_bigquery(sql, *, project_id, location=None):
        captured["location"] = location
        captured["project_id"] = project_id
        return []

    monkeypatch.setattr(script, "query_bigquery", fake_query_bigquery)
    monkeypatch.setattr(script, "load_gcs_observation_rows", lambda **kwargs: [])

    assert script.main(["--project", "predsea-api", "--dry-run"]) == 0
    assert captured["project_id"] == "predsea-api"
    assert captured["location"] == "EU"


def test_build_climatology_query_uses_evidence_source_columns():
    script = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "build_climatology.py")

    query = script.build_climatology_query(
        project="predsea-api",
        dataset="predsea_validation",
        evidence_table="evidence_rows",
        start_date="2019-01-01",
        end_date="2026-01-01",
    )

    assert "source_system" in query
    assert "source_label" in query
    assert "AVG(value)" not in query


def test_aggregate_climatology_rows_combines_raw_rows():
    script = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "build_climatology.py")

    rows = script.aggregate_climatology_rows(
        [
            {
                "provider": "puertos_del_estado",
                "network": "redmar",
                "station_id": "palma",
                "station_name": "Palma",
                "latitude": 39.57,
                "longitude": 2.64,
                "variable": "wind_speed",
                "units": "m/s",
                "sample_time_utc": "2024-06-21T08:00:00Z",
                "value": 4.0,
            },
            {
                "provider": "puertos_del_estado",
                "network": "redmar",
                "station_id": "palma",
                "station_name": "Palma",
                "latitude": 39.57,
                "longitude": 2.64,
                "variable": "wind_speed",
                "units": "m/s",
                "sample_time_utc": "2025-06-21T08:00:00Z",
                "value": 8.0,
            },
        ],
        min_sample_count=2,
        min_history_years=2,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "puertos_del_estado"
    assert row["network"] == "redmar"
    assert row["sample_count"] == 2
    assert row["history_years"] == 2
    assert row["clim_mean"] == 6.0
    assert round(row["clim_stddev"], 6) == 2.828427


def test_load_gcs_observation_rows_reads_validation_archives(monkeypatch):
    script = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "build_climatology.py")

    class FakeBlob:
        def __init__(self, name, text):
            self.name = name
            self._text = text

        def download_as_text(self, encoding="utf-8"):
            return self._text

    class FakeBucket:
        def __init__(self, blobs):
            self._blobs = blobs

        def blob(self, name):
            for blob in self._blobs:
                if blob.name == name:
                    return blob
            raise AssertionError(f"missing blob {name}")

    class FakeClient:
        def __init__(self, blobs):
            self._blobs = blobs

        def bucket(self, bucket_name):
            return FakeBucket(self._blobs)

        def list_blobs(self, bucket, prefix=""):
            return [blob for blob in self._blobs if blob.name.startswith(prefix)]

    blobs = [
        FakeBlob(
            "predictions/2025-06-21/runs/2025-06-21T0800Z/validation/observation_samples.jsonl",
            '{"provider":"puertos_del_estado","network":"redmar","station_id":"palma","station_name":"Palma","latitude":39.57,"longitude":2.64,"variable":"wind_speed","units":"m/s","sample_time_utc":"2025-06-21T08:00:00Z","value":5.0}\n',
        )
    ]
    client = FakeClient(blobs)

    rows = script.load_gcs_observation_rows(
        bucket_name="predsea-daily-outputs",
        prefix="predictions",
        client=client,
        start_date="2025-01-01",
        end_date="2026-01-01",
    )

    assert len(rows) == 1
    assert rows[0]["station_id"] == "palma"
    assert rows[0]["variable"] == "wind_speed"
