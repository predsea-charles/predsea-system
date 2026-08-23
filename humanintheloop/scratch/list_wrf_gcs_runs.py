from google.cloud import storage

client = storage.Client()
bucket_name = "predsea-daily-outputs"

print("Listing WRF NetCDF runs in GCS bucket:")
try:
    blobs = client.list_blobs(bucket_name, prefix="predictions/")
    runs = {}
    for blob in blobs:
        if blob.name.endswith(".nc") or blob.name.endswith(".nc4"):
            # Path usually: predictions/2026-06-04/runs/2026-06-04T1241Z/...
            parts = blob.name.split("/")
            if len(parts) >= 4 and parts[2] == "runs":
                run_date = parts[1]
                run_id = parts[3]
                runs.setdefault(run_date, []).append(run_id)
                
    for run_date, run_ids in sorted(runs.items()):
        print(f"Date: {run_date} -> Run IDs: {sorted(list(set(run_ids)))}")
except Exception as e:
    print(f"Error: {e}")
