import os
import json
import subprocess
from google.cloud import storage

def copy_surgical(date_str):
    print(f"\n--- Surgical Copy for {date_str} ---")
    bucket_name = "predsea-daily-outputs"
    target_bucket_name = "predsea-daily-outputs-prod"
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    
    # 1. Copy latest_run.json and active_gmdss_warnings.json
    for filename in ["latest_run.json", "active_gmdss_warnings.json"]:
        source_blob = f"gs://{bucket_name}/predictions/{date_str}/{filename}"
        target_blob = f"gs://{target_bucket_name}/predictions/{date_str}/{filename}"
        print(f"Copying {filename}...")
        subprocess.run(["gsutil", "cp", source_blob, target_blob], check=False)
    
    # 2. Get run_id
    latest_run_blob = bucket.blob(f"predictions/{date_str}/latest_run.json")
    if not latest_run_blob.exists():
        print(f"latest_run.json not found for {date_str}.")
        return
    
    latest_run_data = json.loads(latest_run_blob.download_as_text())
    run_id = latest_run_data.get("run_id")
    if not run_id:
        print(f"Run ID not found in latest_run.json for {date_str}.")
        return
    
    print(f"Latest Run ID: {run_id}")
    
    # 3. Copy only the latest run folder
    source_run_prefix = f"gs://{bucket_name}/predictions/{date_str}/runs/{run_id}/"
    target_run_prefix = f"gs://{target_bucket_name}/predictions/{date_str}/runs/{run_id}/"
    
    print(f"Copying run folder {run_id}...")
    subprocess.run(["gsutil", "-m", "cp", "-r", source_run_prefix, target_run_prefix], check=True)

if __name__ == "__main__":
    for day in range(1, 12):
        date_str = f"2026-07-{day:02d}"
        try:
            copy_surgical(date_str)
        except Exception as e:
            print(f"Error copying {date_str}: {e}")
