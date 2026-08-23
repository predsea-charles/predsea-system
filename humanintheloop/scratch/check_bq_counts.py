import os
from google.cloud import bigquery

def check_dataset_counts(dataset_id):
    client = bigquery.Client()
    try:
        query = f"SELECT count(*) as total, max(ingested_at_utc) as latest FROM `{dataset_id}.evidence_rows`"
        results = client.query(query).to_dataframe()
        print(f"Dataset: {dataset_id}")
        print(results)
        
        query_recent = f"SELECT record_type, count(*) as count FROM `{dataset_id}.evidence_rows` WHERE ingested_at_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY) GROUP BY record_type"
        results_recent = client.query(query_recent).to_dataframe()
        print("Recent records (7 days):")
        print(results_recent)
        print("-" * 40)
    except Exception as e:
        print(f"Error checking {dataset_id}: {e}")

if __name__ == "__main__":
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or "predsea-api"
    check_dataset_counts(f"{project_id}.predsea_validation_prod")
    check_dataset_counts(f"{project_id}.predsea_validation")
