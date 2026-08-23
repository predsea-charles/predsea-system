from google.cloud import storage

client = storage.Client()
bucket_name = "predsea-daily-outputs"

print(f"Listing subdirectories/prefixes in '{bucket_name}':")
try:
    # We can use the delimiter to list prefixes (which represent directories)
    iterator = client.list_blobs(bucket_name, delimiter="/")
    list(iterator) # need to consume iterator to populate prefixes
    print("Top-level directories:")
    for prefix in iterator.prefixes:
        print(f"- {prefix}")
        
        # Now list second-level
        sub_iterator = client.list_blobs(bucket_name, prefix=prefix, delimiter="/")
        list(sub_iterator)
        for sub_prefix in sub_iterator.prefixes:
            print(f"  - {sub_prefix}")
except Exception as e:
    print(f"Error: {e}")
