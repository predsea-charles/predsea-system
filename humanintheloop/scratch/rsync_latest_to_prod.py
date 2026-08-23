import os
import json
import subprocess
from google.cloud import storage

def copy_rsync(date_str):
    print(f"\n--- Rsync for {date_str} ---")
    bucket_name = "predsea-daily-outputs"
    target_bucket_name = "predsea-daily-outputs-prod"
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    
    # 1. Get run_id
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
    
    # 2. Rsync day folder but exclude 'runs' first (to get root files)
    # Actually, simpler: rsync individual files then the run folder
    
    root_files = ["latest_run.json", "active_gmdss_warnings.json"]
    for f in root_files:
        src = f"gs://{bucket_name}/predictions/{date_str}/{f}"
        dst = f"gs://{target_bucket_name}/predictions/{date_str}/{f}"
        subprocess.run(["gsutil", "cp", src, dst], check=False)

    # 3. Rsync the specific run folder
    source_run = f"gs://{bucket_name}/predictions/{date_str}/runs/{run_id}/"
    target_run = f"gs://{target_bucket_name}/predictions/{date_str}/runs/{run_id}/"
    
    print(f"Rsyncing run folder {run_id}...")
    # Using -o to disable multiprocessing on Mac and -m for multithreading
    subprocess.run(["gsutil", "-o", "GSUtil:parallel_process_count=1", "-m", "rsync", "-r", source_run, target_run], check=True)

if __name__ == "__main__":
    for day in range(1, 12):
        date_str = f"2026-07-{day:02d}"
        try:
            copy_rsync(date_str)
        except Exception as e:
            print(f"Error rsyncing {date_str}: {e}")
