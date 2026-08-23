import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "monitor_provider_releases.py"
SPEC = importlib.util.spec_from_file_location("monitor_provider_releases", SCRIPT_PATH)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


def test_parse_socib_runs_catalog_returns_latest_runs():
    xml = """
    <catalog>
      <dataset name="sapo_ib_RUN_2026-06-05T00:00:00Z" />
      <dataset name="sapo_ib_RUN_2026-06-04T00:00:00Z" />
      <dataset name="sapo_ib_RUN_2026-06-03T00:00:00Z" />
    </catalog>
    """

    runs = monitor.parse_socib_runs_catalog(xml, limit=2)

    assert runs == ["2026-06-05T00:00:00Z", "2026-06-04T00:00:00Z"]


def test_extract_copernicus_update_metadata_from_catalog_dump():
    catalog = {
        "products": [
            {
                "datasets": [
                    {
                        "dataset_id": "cmems_mod_med_wav_anfc_4.2km_PT1H-i",
                        "versions": [
                            {
                                "parts": [
                                    {
                                        "released_date": "2023-11-30T11:00:00.000Z",
                                        "arco_updated_date": "2026-06-05T02:03:27.316Z",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        ]
    }

    metadata = monitor.extract_copernicus_update_metadata(catalog)

    assert metadata["released_date"] == "2023-11-30T11:00:00.000Z"
    assert metadata["arco_updated_date"] == "2026-06-05T02:03:27.316Z"


def test_write_probe_outputs_timestamped_json_and_jsonl(tmp_path):
    probe_time = datetime(2026, 6, 5, 8, 30, tzinfo=timezone.utc)
    records = [
        {
            "provider": "socib",
            "dataset": "sapo_ib",
            "available": True,
            "latest_model_run": "2026-06-05T00:00:00Z",
        }
    ]

    output_path = monitor.write_probe_outputs(tmp_path, records, probe_time=probe_time)

    assert output_path == tmp_path / "2026-06-05" / "provider_release_probe_2026-06-05T0830Z.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["probe_time_utc"] == "2026-06-05T08:30:00Z"
    assert payload["records"] == records

    jsonl_path = tmp_path / "2026-06-05" / "provider_release_probes.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == payload
