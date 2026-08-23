from google.cloud import storage

client = storage.Client()
buckets = ["predsea-daily-outputs", "predsea-hpc-outputs"]

for bucket_name in buckets:
    print(f"\nSearching '.nc' or 'wind' in '{bucket_name}':")
    try:
        blobs = client.list_blobs(bucket_name)
        count = 0
        for blob in blobs:
            name_lower = blob.name.lower()
            if ".nc" in name_lower or "wind" in name_lower or "wrf" in name_lower or "forecast" in name_lower:
                print(f"- {blob.name} (Size: {blob.size} bytes)")
                count += 1
                if count >= 50:
                    print("... too many results, truncating search")
                    break
        if count == 0:
            print("No matching files found.")
    except Exception as e:
        print(f"Error: {e}")
