from google.cloud import storage

client = storage.Client()
buckets = ["predsea-daily-outputs", "predsea-hpc-outputs"]

for bucket_name in buckets:
    print(f"\nListing files in bucket '{bucket_name}':")
    try:
        bucket = client.bucket(bucket_name)
        blobs = list(client.list_blobs(bucket_name, max_results=30))
        for blob in blobs:
            print(f"- {blob.name} (Size: {blob.size} bytes)")
    except Exception as e:
        print(f"Error: {e}")
