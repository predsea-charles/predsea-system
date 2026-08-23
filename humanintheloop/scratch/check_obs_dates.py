from google.cloud import bigquery

client = bigquery.Client()
project_id = client.project
dataset = "predsea_validation"
table = "evidence_rows"
table_ref = f"{project_id}.{dataset}.{table}"

query = f"""
    SELECT
      DATE(observed_at_utc) AS obs_date,
      COUNT(*) AS cnt
    FROM `{table_ref}`
    WHERE record_type = 'observation'
    GROUP BY obs_date
    ORDER BY obs_date DESC
    LIMIT 30
"""

print("Checking most recent observation dates...")
try:
    for row in client.query(query).result():
        print(f"Date: {row.obs_date} | Count: {row.cnt}")
except Exception as e:
    print(f"Query failed: {e}")
