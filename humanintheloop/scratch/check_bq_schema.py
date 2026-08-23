import os
from google.cloud import bigquery

def check_schema(dataset_id, table_id):
    client = bigquery.Client()
    try:
        table = client.get_table(f"{dataset_id}.{table_id}")
        print(f"Table: {dataset_id}.{table_id}")
        print(f"Number of fields: {len(table.schema)}")
        field_names = [field.name for field in table.schema]
        print(f"Contains 'freshness_status': {'freshness_status' in field_names}")
        # Print a few fields to verify
        print(f"First 5 fields: {field_names[:5]}")
        print(f"Last 5 fields: {field_names[-5:]}")
    except Exception as e:
        print(f"Error checking schema: {e}")

if __name__ == "__main__":
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or "predsea-api"
    check_schema(f"{project_id}.predsea_validation", "evidence_rows")
    check_schema(f"{project_id}.predsea_validation_prod", "evidence_rows")
