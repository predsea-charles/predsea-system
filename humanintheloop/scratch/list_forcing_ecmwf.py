from google.cloud import storage

client = storage.Client()
bucket_name = "predsea-daily-outputs"

print("Listing files under forcing/ecmwf/:")
try:
    blobs = list(client.list_blobs(bucket_name, prefix="forcing/ecmwf/", max_results=50))
    for b in blobs:
        print(f"- {b.name} (Size: {b.size} bytes)")
except Exception as e:
    print(f"Error: {e}")

print("\nListing some files under predictions/2026-06-04/:")
try:
    blobs = list(client.list_blobs(bucket_name, prefix="predictions/2026-06-04/", max_results=10))
    for b in blobs:
        print(f"- {b.name} (Size: {b.size} bytes)")
except Exception as e:
    print(f"Error: {e}")
