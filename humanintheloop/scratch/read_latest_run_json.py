from google.cloud import storage
import json

client = storage.Client()
bucket_name = "predsea-daily-outputs"
bucket = client.bucket(bucket_name)

blob = bucket.blob("predictions/2026-06-04/latest_run.json")
try:
    content = blob.download_as_text()
    data = json.loads(content)
    print("latest_run.json contents:")
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error downloading: {e}")
