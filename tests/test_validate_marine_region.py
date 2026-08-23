from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_marine_region import validate_region


REGION = Path("simulation/marine/regions/balearic_1km.json")


def test_balearic_region_profile_passes_preflight():
    report = validate_region(REGION)
    assert report["status"] == "succeeded"
    assert report["region_id"] == "balearic_1km"


def test_region_preflight_rejects_invalid_ranges_and_timestep(tmp_path):
    region = json.loads(REGION.read_text())
    region["bbox"]["longitude_min"] = 6.0
    region["models"]["swan"]["computational_timestep_minutes"] = 7
    region["models"]["croco"]["physical_ranges"]["eastward_current"] = [5.0, -5.0]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(region))

    report = validate_region(path)

    assert report["status"] == "failed"
    assert "longitude bounds are invalid or unordered" in report["errors"]
    assert (
        "SWAN computational timestep must divide the publication interval"
        in report["errors"]
    )
    assert (
        "croco.eastward_current has invalid physical range" in report["errors"]
    )
