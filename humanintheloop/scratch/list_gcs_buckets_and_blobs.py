from google.cloud import storage

client = storage.Client()
buckets = list(client.list_buckets())

print("Available GCS Buckets:")
for b in buckets:
    print(f"- {b.name}")
    
    # List top-level or some files to find wind forecasts
    print(f"  Listing files in bucket '{b.name}':")
    try:
        blobs = list(client.list_blobs(b.name, max_results=10))
        for blob in blobs:
            print(f"    - {blob.name} (Size: {blob.size} bytes)")
    except Exception as e:
        print(f"    Error listing: {e}")
