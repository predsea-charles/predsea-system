from google.cloud import bigquery

client = bigquery.Client()
project_id = client.project
dataset = "predsea_validation"
table = "evidence_rows"
table_ref = f"{project_id}.{dataset}.{table}"

query = f"""
    SELECT
      DATE(observed_at_utc) as obs_date,
      variable,
      COUNT(*) AS cnt
    FROM `{table_ref}`
    WHERE record_type = 'observation'
      AND provider = 'puertos_del_estado'
    GROUP BY obs_date, variable
    ORDER BY cnt DESC
    LIMIT 30
"""

print("Checking top observation dates for puertos_del_estado...")
try:
    for row in client.query(query).result():
        print(f"Date: {row.obs_date} | Var: {row.variable:20} | Count: {row.cnt}")
except Exception as e:
    print(f"Query failed: {e}")
