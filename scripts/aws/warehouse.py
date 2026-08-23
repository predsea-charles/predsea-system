"""Parquet evidence writer for the Athena-backed PredSea warehouse."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pandas as pd


def write_evidence_rows(rows: list[dict], *, bucket: str | None = None, s3_client=None) -> str:
    if not rows:
        raise ValueError("At least one evidence row is required")
    frame = pd.DataFrame(rows)
    if "run_date" not in frame or frame["run_date"].isna().any():
        raise ValueError("Every evidence row must have run_date")
    if "run_id" not in frame or frame["run_id"].isna().any() or (frame["run_id"].astype(str).str.strip() == "").any():
        raise ValueError("Every evidence row must have run_id")
    now = pd.Timestamp(datetime.now(timezone.utc))
    if "ingested_at_utc" not in frame:
        frame["ingested_at_utc"] = now
    else:
        frame["ingested_at_utc"] = pd.to_datetime(frame["ingested_at_utc"], utc=True, errors="coerce").fillna(now)
    for timestamp_column in ("target_time_utc", "observed_at_utc"):
        if timestamp_column in frame:
            frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], utc=True, errors="coerce")
    for numeric_column in ("value", "lead_time_hours", "latitude", "longitude"):
        if numeric_column in frame:
            frame[numeric_column] = pd.to_numeric(frame[numeric_column], errors="coerce")
    run_dates = set(frame["run_date"].astype(str))
    if len(run_dates) != 1:
        raise ValueError("One Parquet object may contain only one run_date partition")
    run_date = run_dates.pop()
    run_ids = set(frame["run_id"].astype(str))
    if len(run_ids) != 1:
        raise ValueError("One Parquet object may contain only one run_id")
    run_id = run_ids.pop()
    if not all(character.isalnum() or character in "-_.T:Z" for character in run_id):
        raise ValueError("run_id contains characters that are unsafe for an S3 key")
    key = f"warehouse/evidence_rows/run_date={run_date}/run_id={run_id}/evidence.parquet"
    target_bucket = bucket or os.environ["PREDSEA_S3_BUCKET"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "evidence.parquet"
        frame.to_parquet(path, engine="pyarrow", index=False)
        (s3_client or boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-west-1"))).upload_file(
            str(path), target_bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"}
        )
    return f"s3://{target_bucket}/{key}"
