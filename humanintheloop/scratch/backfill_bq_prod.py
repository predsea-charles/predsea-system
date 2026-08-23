import os
import sys
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from google.cloud import storage

# Add humanintheloop to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import bigquery_export

def backfill_day(date_str):
    print(f"\n--- Backfilling {date_str} ---")
    bucket_name = "predsea-daily-outputs"
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    
    # 1. Get latest_run.json
    latest_run_blob = bucket.blob(f"predictions/{date_str}/latest_run.json")
    if not latest_run_blob.exists():
        print(f"latest_run.json not found for {date_str}. Skipping.")
        return
    
    latest_run_data = json.loads(latest_run_blob.download_as_text())
    run_id = latest_run_data.get("run_id")
    if not run_id:
        print(f"Run ID not found in latest_run.json for {date_str}. Skipping.")
        return
    
    print(f"Latest Run ID: {run_id}")
    
    # 2. Download validation/ artifacts
    with tempfile.TemporaryDirectory() as temp_dir:
        local_run_dir = Path(temp_dir)
        validation_dir = local_run_dir / "validation"
        validation_dir.mkdir()
        
        prefix = f"predictions/{date_str}/runs/{run_id}/validation/"
        blobs = storage_client.list_blobs(bucket_name, prefix=prefix)
        
        found_artifacts = False
        for blob in blobs:
            filename = os.path.basename(blob.name)
            if not filename:
                continue
            local_path = validation_dir / filename
            blob.download_to_filename(str(local_path))
            print(f"Downloaded {filename}")
            found_artifacts = True
            
        if not found_artifacts:
            print(f"No validation artifacts found in {prefix}. Skipping.")
            return
            
        # 3. Export to BigQuery
        print(f"Exporting to BigQuery (PREDSEA_ENV=prod)...")
        os.environ["PREDSEA_ENV"] = "prod"
        # Force production project just in case
        os.environ["GOOGLE_CLOUD_PROJECT"] = "predsea-api"
        
        result = bigquery_export.export_validation_archive_to_bigquery(
            run_dir=str(local_run_dir),
            dry_run=False
        )
        print(f"Result: {result.get('status')} - {result.get('reason', 'OK')}")
        print(f"Rows: obs={result.get('observation_rows', 0)}, forecast={result.get('forecast_rows', 0)}, exported={result.get('exported_rows', 0)}")
        
        # 4. Export Station Metadata
        if hasattr(bigquery_export, "export_station_metadata_to_bigquery"):
             # Download station_metadata.jsonl if it exists in the same run dir
            metadata_blob = bucket.blob(f"predictions/{date_str}/runs/{run_id}/station_metadata.jsonl")
            if metadata_blob.exists():
                metadata_blob.download_to_filename(str(local_run_dir / "station_metadata.jsonl"))
                print(f"Exporting station metadata...")
                sm_result = bigquery_export.export_station_metadata_to_bigquery(
                    run_dir=str(local_run_dir),
                    dry_run=False
                )
                print(f"Metadata Result: {sm_result.get('status')}")

if __name__ == "__main__":
    for day in range(1, 12):
        date_str = f"2026-07-{day:02d}"
        try:
            backfill_day(date_str)
        except Exception as e:
            print(f"Error backfilling {date_str}: {e}")
