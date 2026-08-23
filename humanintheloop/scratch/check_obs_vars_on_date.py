from google.cloud import bigquery

client = bigquery.Client()
project_id = client.project
dataset = "predsea_validation"
table = "evidence_rows"
table_ref = f"{project_id}.{dataset}.{table}"

query = f"""
    SELECT
      provider,
      variable,
      COUNT(*) AS cnt
    FROM `{table_ref}`
    WHERE record_type = 'observation'
      AND DATE(observed_at_utc) = '2026-06-24'
    GROUP BY provider, variable
    ORDER BY cnt DESC
"""

print("Checking variables on 2026-06-24...")
try:
    for row in client.query(query).result():
        print(f"Provider: {row.provider} | Var: {row.variable} | Count: {row.cnt}")
except Exception as e:
    print(f"Query failed: {e}")
