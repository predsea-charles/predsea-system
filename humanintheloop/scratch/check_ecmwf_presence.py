from google.cloud import bigquery

client = bigquery.Client()
project_id = client.project
dataset = "predsea_validation"
table = "evidence_rows"
table_ref = f"{project_id}.{dataset}.{table}"

query = f"""
    SELECT
      record_type,
      provider,
      source_system,
      forecast_source_id,
      variable,
      COUNT(*) AS cnt
    FROM `{table_ref}`
    WHERE LOWER(provider) LIKE '%ecmwf%'
       OR LOWER(source_system) LIKE '%ecmwf%'
       OR LOWER(forecast_source_id) LIKE '%ecmwf%'
    GROUP BY record_type, provider, source_system, forecast_source_id, variable
"""

print("Searching for any occurrences of 'ecmwf' in provider/source fields...")
try:
    results = list(client.query(query).result())
    if not results:
        print("No records found with 'ecmwf' in provider, source_system, or forecast_source_id.")
    else:
        for row in results:
            print(f"Type: {row.record_type} | Provider: {row.provider} | Source: {row.source_system} | ID: {row.forecast_source_id} | Var: {row.variable} | Count: {row.cnt}")
except Exception as e:
    print(f"Query failed: {e}")
