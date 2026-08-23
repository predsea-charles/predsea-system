from google.cloud import storage

client = storage.Client()
bucket_name = "predsea-daily-outputs"
bucket = client.bucket(bucket_name)

print("Searching for NetCDF files in predictions/ across all dates:")
blobs = client.list_blobs(bucket_name, prefix="predictions/")
count = 0
for b in blobs:
    if b.name.endswith(".nc") or b.name.endswith(".nc4"):
        print(f"- {b.name} (Size: {b.size} bytes)")
        count += 1
        if count >= 100:
            print("Truncated at 100 files.")
            break
if count == 0:
    print("No NetCDF files found in predictions/ anywhere!")
