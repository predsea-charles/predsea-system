import sys
from pathlib import Path
from google.cloud import bigquery

# Resolve project ID
client = bigquery.Client()
project_id = client.project
dataset = "predsea_validation"
table = "evidence_rows"
table_ref = f"{project_id}.{dataset}.{table}"

print(f"Project ID: {project_id}")
print(f"Table Ref: {table_ref}")

# Query 1: distinct providers and their record count
query1 = f"""
    SELECT
      record_type,
      CASE
        WHEN COALESCE(provider, source_system, forecast_source_id) IS NOT NULL THEN COALESCE(provider, source_system, forecast_source_id)
        WHEN variable IN ('current_speed', 'current_direction') THEN 'predsea_roms'
        WHEN variable IN ('wave_height', 'wave_direction') THEN 'predsea_swan'
        WHEN variable IN ('wind_speed', 'wind_direction', 'air_temperature', 'sea_level_pressure') THEN 'predsea_wrf'
        ELSE NULL
      END AS provider,
      COUNT(*) AS cnt,
      MIN(COALESCE(target_time_utc, observed_at_utc)) as min_time,
      MAX(COALESCE(target_time_utc, observed_at_utc)) as max_time
    FROM `{table_ref}`
    GROUP BY record_type, provider
    ORDER BY record_type, cnt DESC
"""

print("Running Query 1...")
try:
    for row in client.query(query1).result():
        print(f"Type: {row.record_type:12} | Provider: {str(row.provider):20} | Count: {row.cnt:8} | Range: {row.min_time} to {row.max_time}")
except Exception as e:
    print(f"Query 1 failed: {e}")

# Query 2: Let's find dates where we have observations and their variable breakdown
query2 = f"""
    SELECT
      DATE(observed_at_utc) AS obs_date,
      variable,
      COUNT(*) AS cnt
    FROM `{table_ref}`
    WHERE record_type = 'observation'
    GROUP BY obs_date, variable
    ORDER BY obs_date DESC, cnt DESC
    LIMIT 20
"""

print("\nRunning Query 2 (Recent Observations)...")
try:
    for row in client.query(query2).result():
        print(f"Date: {row.obs_date} | Variable: {row.variable:20} | Count: {row.cnt:5}")
except Exception as e:
    print(f"Query 2 failed: {e}")
