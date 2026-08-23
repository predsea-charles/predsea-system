#!/usr/bin/env python3
"""Convert PredSea validation JSONL artifacts to partitioned S3 Parquet."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.aws.warehouse import write_evidence_rows


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(row: dict, run_date: str, run_id: str) -> dict:
    return {
        "record_type": row.get("record_type"),
        "run_id": run_id,
        "run_date": row.get("run_date") or run_date,
        "reference_station_id": row.get("reference_station_id") or row.get("truth_station_id") or row.get("station_id"),
        "station_id": row.get("station_id") or row.get("truth_station_id"),
        "variable": row.get("variable"),
        "value": row.get("value"),
        "units": row.get("units"),
        "provider": row.get("provider") or row.get("forecast_source_id") or row.get("source_system") or row.get("ocean_source"),
        "target_time_utc": row.get("target_time_utc"),
        "observed_at_utc": row.get("observed_at_utc"),
        "ingested_at_utc": row.get("ingested_at_utc") or row.get("collected_at_utc"),
        "lead_time_hours": row.get("lead_time_hours"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "station_name": row.get("station_name"),
        "station_kind": row.get("station_kind"),
        "network": row.get("network"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--bucket", default=os.getenv("PREDSEA_S3_BUCKET"))
    args = parser.parse_args()
    validation = args.run_dir / "validation"
    rows = []
    for name in ("observation_samples.jsonl", "forecast_index.jsonl", "station_metadata.jsonl"):
        rows.extend(normalize(row, args.run_date, args.run_id) for row in read_rows(validation / name))
    if not rows:
        print("No validation rows found; Athena export skipped.")
        return 0
    print(write_evidence_rows(rows, bucket=args.bucket))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
