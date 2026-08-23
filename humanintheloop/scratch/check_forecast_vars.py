from google.cloud import bigquery

client = bigquery.Client()
project_id = client.project
dataset = "predsea_validation"
table = "evidence_rows"
table_ref = f"{project_id}.{dataset}.{table}"

query = f"""
    SELECT
      CASE
        WHEN COALESCE(provider, source_system, forecast_source_id) IS NOT NULL THEN COALESCE(provider, source_system, forecast_source_id)
        WHEN variable IN ('current_speed', 'current_direction') THEN 'predsea_roms'
        WHEN variable IN ('wave_height', 'wave_direction') THEN 'predsea_swan'
        WHEN variable IN ('wind_speed', 'wind_direction', 'air_temperature', 'sea_level_pressure') THEN 'predsea_wrf'
        ELSE NULL
      END AS provider,
      variable,
      COUNT(*) AS cnt,
      MIN(target_time_utc) as min_target,
      MAX(target_time_utc) as max_target
    FROM `{table_ref}`
    WHERE record_type = 'forecast'
    GROUP BY provider, variable
    ORDER BY provider, cnt DESC
"""

print("Finding all forecast variables and their providers...")
try:
    for row in client.query(query).result():
        print(f"Provider: {str(row.provider):20} | Var: {row.variable:20} | Count: {row.cnt:8} | Range: {row.min_target} to {row.max_target}")
except Exception as e:
    print(f"Failed: {e}")
