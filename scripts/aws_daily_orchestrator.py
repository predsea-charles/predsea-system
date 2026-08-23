#!/usr/bin/env python3
"""AWS-native daily control plane: forcing, Spot simulation, and publication."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
MARINE_REGIONS = (
    "alboran_1km",
    "algerian_1km",
    "balearic_1km",
    "gulf_of_lion_1km",
    "tyrrhenian_1km",
)
NATIVE_MARINE_FILES = (
    "cmems_croco_currents_3d.nc",
    "cmems_croco_temperature_3d.nc",
    "cmems_croco_salinity_3d.nc",
    "cmems_croco_sea_level.nc",
    "cmems_swan_boundary.nc",
)


def run(command: list[str], *, dry_run: bool = False) -> None:
    print("Running:", " ".join(command))
    if not dry_run:
        subprocess.run(command, cwd=ROOT, check=True)


def load_runtime_secrets() -> None:
    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "eu-west-1"))
    for name in ("AEMET_API_KEY", "SOCIB_API_KEY", "COPERNICUS_USERNAME", "COPERNICUS_PASSWORD"):
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
            if name.startswith("COPERNICUS_"):
                raise RuntimeError(f"Required secret predsea/{name} has no value")


def stage_native_marine_forcing(
    bucket: str,
    run_date: str,
    forecast_hours: int,
    *,
    dry_run: bool = False,
    s3=None,
) -> None:
    """Fetch and validate every regional CROCO/SWAN input before EC2 launch."""
    client = s3 or (None if dry_run else boto3.client(
        "s3", region_name=os.getenv("AWS_REGION", "eu-west-1")
    ))
    with tempfile.TemporaryDirectory(prefix="predsea-native-marine-") as temp_dir:
        staging_root = Path(temp_dir)
        for region in MARINE_REGIONS:
            output_dir = staging_root / region
            command = [
                sys.executable,
                "scripts/fetch_native_marine_forcing.py",
                "--run-date", run_date,
                "--forecast-hours", str(forecast_hours),
                "--region", f"simulation/marine/regions/{region}.json",
                "--output-dir", str(output_dir),
                "--models", "croco", "swan",
                "--overwrite",
            ]
            if dry_run:
                command.append("--dry-run")
            run(command, dry_run=dry_run)
            if dry_run:
                continue

            manifest_path = output_dir / "forcing_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            if manifest.get("status") != "succeeded" or manifest.get("region_id") != region:
                raise RuntimeError(
                    f"Native marine forcing validation failed for {region}: {manifest}"
                )
            for filename in NATIVE_MARINE_FILES:
                path = output_dir / filename
                if not path.is_file() or path.stat().st_size == 0:
                    raise RuntimeError(f"Validated native marine artifact is missing: {path}")
                stem = path.stem
                client.upload_file(
                    str(path),
                    bucket,
                    f"forcing/cmems/{run_date}/{stem}_{region}.nc",
                    ExtraArgs={"ServerSideEncryption": "AES256"},
                )
            client.upload_file(
                str(manifest_path),
                bucket,
                f"forcing/cmems/{run_date}/forcing_manifest_{region}.json",
                ExtraArgs={"ServerSideEncryption": "AES256"},
            )


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
    if not args.dry_run: load_runtime_secrets()
    publish_status(bucket, run_date, run_id, "STARTED", "AWS daily run started") if not args.dry_run else None
    try:
        common = [f"--run-date={run_date}", f"--lead-hours={args.forecast_hours}", f"--s3-bucket={bucket}", "--gcs-bucket="]
        run([sys.executable, "scripts/fetch_ecmwf_forcing.py", *common], dry_run=args.dry_run)
        stage_native_marine_forcing(
            bucket, run_date, args.forecast_hours, dry_run=args.dry_run
        )
        run([sys.executable, "scripts/aws_orchestrator.py", f"--run-date={run_date}", f"--run-id={run_id}", f"--forecast-hours={args.forecast_hours}", f"--bucket={bucket}"], dry_run=args.dry_run)
        run([sys.executable, "scripts/generate_daily_briefing.py", f"--date={run_date}", f"--run-id={run_id}", "--skip-bigquery", "--publication-phase=high_resolution", "--wrf-status=complete"], dry_run=args.dry_run)
        run([sys.executable, "scripts/export_validation_to_athena.py", f"--run-dir=predictions/{run_date}/runs/{run_id}", f"--run-date={run_date}", f"--run-id={run_id}", f"--bucket={bucket}"], dry_run=args.dry_run)
        if not args.dry_run:
            local_run = ROOT / "predictions" / run_date / "runs" / run_id
            if local_run.exists():
                run(["aws", "s3", "sync", str(local_run), f"s3://{bucket}/predictions/{run_date}/runs/{run_id}/", "--only-show-errors"])
            publish_status(bucket, run_date, run_id, "SUCCEEDED", "AWS daily run completed")
        return 0
    except Exception as error:
        if not args.dry_run: publish_status(bucket, run_date, run_id, "FAILED", str(error))
        raise


if __name__ == "__main__": raise SystemExit(main())
