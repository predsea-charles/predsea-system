import os
from google.cloud import bigquery

def list_tables(dataset_id):
    client = bigquery.Client()
    try:
        tables = list(client.list_tables(dataset_id))
        print(f"Tables in {dataset_id}:")
        for table in tables:
            print(f"- {table.table_id}")
    except Exception as e:
        print(f"Error listing tables in {dataset_id}: {e}")

if __name__ == "__main__":
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or "predsea-api"
    list_tables(f"{project_id}.predsea_validation_prod")
    list_tables(f"{project_id}.predsea_validation")
