from google.cloud import bigquery

client = bigquery.Client()
project_id = client.project
dataset = "predsea_validation"
table = "evidence_rows"
table_ref = f"{project_id}.{dataset}.{table}"

query = f"""
    SELECT
      provider,
      source_system,
      forecast_source_id,
      COUNT(*) AS cnt,
      MIN(target_time_utc) as min_target,
      MAX(target_time_utc) as max_target
    FROM `{table_ref}`
    WHERE record_type = 'forecast'
    GROUP BY provider, source_system, forecast_source_id
    ORDER BY cnt DESC
"""

print("Running Query to find all distinct forecast fields...")
try:
    for row in client.query(query).result():
        print(f"Provider: {str(row.provider):20} | SourceSystem: {str(row.source_system):20} | ForecastSourceId: {str(row.forecast_source_id):20} | Count: {row.cnt:8} | Range: {row.min_target} to {row.max_target}")
except Exception as e:
    print(f"Failed: {e}")
