from __future__ import annotations

import json

from scripts.validate_observation_registry import validate_registry


def test_repository_observation_registry_is_extensible_and_valid():
    from pathlib import Path

    report = validate_registry(
        Path("simulation/quality/observation_registry.json"), environment="test"
    )
    assert report["status"] == "succeeded"
    assert report["active_source_count"] >= 3


def test_registry_rejects_duplicate_station_source_ids(tmp_path):
    path = tmp_path / "registry.json"
    source = {
        "source_id": "new_buoy_network",
        "provider": "provider",
        "connector": "json",
        "discovery_mode": "catalog",
        "enabled_environments": ["test"],
        "variables": ["wave_height"],
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": "predsea.observation_registry.v1",
                "sources": [source, source],
            }
        )
    )
    report = validate_registry(path, environment="test")
    assert report["status"] == "failed"
    assert "duplicate source_id" in " ".join(report["errors"])
