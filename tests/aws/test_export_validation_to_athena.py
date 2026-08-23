from scripts.export_validation_to_athena import normalize


def test_normalize_adds_explicit_run_lineage():
    row = normalize(
        {"record_type": "observation", "station_id": "station-1", "value": 2.5},
        "2026-08-23",
        "2026-08-23T0300Z",
    )

    assert row["run_date"] == "2026-08-23"
    assert row["run_id"] == "2026-08-23T0300Z"
    assert row["station_id"] == "station-1"
