#!/usr/bin/env python3
"""AWS-native daily control plane: ECMWF forcing, WRF, WW3, and publication."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

try:
    from scripts.aws.run_cost_ledger import RunCostLedger
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from aws.run_cost_ledger import RunCostLedger

ROOT = Path(__file__).resolve().parents[1]
WW3_REGION = "western_mediterranean_2km"


def run(command: list[str], *, dry_run: bool = False) -> None:
    print("Running:", " ".join(command))
    if not dry_run:
        subprocess.run(command, cwd=ROOT, check=True)


def load_runtime_secrets() -> None:
    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "eu-west-1"))
    # AEMET and SOCIB are optional validation data sources (used by generate_daily_briefing.py).
    # Copernicus Marine credentials are NOT required — the WRF+WW3 pipeline does not use them.
    for name in ("AEMET_API_KEY", "SOCIB_API_KEY"):
        if os.getenv(name):
            continue
        try:
            value = sm.get_secret_value(SecretId=f"predsea/{name}").get("SecretString")
            if value:
                try:
                    decoded = json.loads(value)
                    if isinstance(decoded, dict):
                        value = decoded.get(name) or decoded.get("value")
                except json.JSONDecodeError:
                    pass
                if value:
                    os.environ[name] = str(value)
        except sm.exceptions.ResourceNotFoundException:
            print(f"[secrets] predsea/{name} not found — skipping (optional)")




def publish_status(bucket: str, run_date: str, run_id: str, status: str, message: str, *, s3=None) -> None:
    payload = json.dumps({"run_date": run_date, "run_id": run_id, "status": status, "message": message, "updated_at_utc": datetime.now(timezone.utc).isoformat()}, indent=2).encode()
    client = s3 or boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-west-1"))
    for key in (f"predictions/{run_date}/runs/{run_id}/publication_status.json", f"predictions/{run_date}/latest_status.json"):
        client.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="application/json", ServerSideEncryption="AES256")


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--run-date"); p.add_argument("--run-id"); p.add_argument("--forecast-hours", type=int, default=int(os.getenv("PREDSEA_FORECAST_HOURS", "72"))); p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(); now = datetime.now(timezone.utc); run_date = args.run_date or now.date().isoformat(); run_id = args.run_id or now.strftime("%Y-%m-%dT%H%MZ")
    if args.forecast_hours != 72:
        p.error("AWS production runs are fixed at 72 forecast hours")
    bucket = os.getenv("PREDSEA_S3_BUCKET", "predsea-daily-outputs")
    ledger = None
    if not args.dry_run:
        load_runtime_secrets()
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-west-1"))
        ledger = RunCostLedger(
            bucket, run_date, run_id, s3,
            provisional_s3_cost_usd=os.getenv("PREDSEA_PROVISIONAL_S3_COST_USD"),
            provisional_cloudwatch_cost_usd=os.getenv("PREDSEA_PROVISIONAL_CLOUDWATCH_COST_USD"),
        )
        ledger.publish()
        publish_status(bucket, run_date, run_id, "STARTED", "AWS daily run started", s3=s3)
    try:
        common = [f"--run-date={run_date}", f"--lead-hours={args.forecast_hours}", f"--s3-bucket={bucket}", "--gcs-bucket="]
        run([sys.executable, "scripts/fetch_ecmwf_forcing.py", *common], dry_run=args.dry_run)
        run([sys.executable, "scripts/aws_orchestrator.py", f"--run-date={run_date}", f"--run-id={run_id}", f"--forecast-hours={args.forecast_hours}", f"--bucket={bucket}"], dry_run=args.dry_run)
        run([sys.executable, "scripts/generate_daily_briefing.py", f"--date={run_date}", f"--run-id={run_id}", "--skip-bigquery", "--publication-phase=high_resolution", "--wrf-status=complete"], dry_run=args.dry_run)
        run([sys.executable, "scripts/export_validation_to_athena.py", f"--run-dir=predictions/{run_date}/runs/{run_id}", f"--run-date={run_date}", f"--run-id={run_id}", f"--bucket={bucket}"], dry_run=args.dry_run)
        if not args.dry_run:
            local_run = ROOT / "predictions" / run_date / "runs" / run_id
            if local_run.exists():
                run(["aws", "s3", "sync", str(local_run), f"s3://{bucket}/predictions/{run_date}/runs/{run_id}/", "--only-show-errors"])
            publish_status(bucket, run_date, run_id, "SUCCEEDED", "AWS daily run completed", s3=s3)
            ledger.finish("SUCCEEDED", "AWS daily run completed")
        return 0
    except Exception as error:
        if not args.dry_run:
            publish_status(bucket, run_date, run_id, "FAILED", str(error), s3=s3)
            ledger.finish("FAILED", str(error))
        raise


if __name__ == "__main__": raise SystemExit(main())
