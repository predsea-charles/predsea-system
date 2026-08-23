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
      COUNT(*) AS cnt,
      MIN(observed_at_utc) as min_obs,
      MAX(observed_at_utc) as max_obs
    FROM `{table_ref}`
    WHERE record_type = 'observation'
      AND DATE(observed_at_utc) = '2026-04-29'
    GROUP BY provider, variable
"""

print("Checking observations on 2026-04-29...")
try:
    results = list(client.query(query).result())
    if not results:
        print("No observations found on 2026-04-29.")
    else:
        for row in results:
            print(f"Provider: {row.provider} | Var: {row.variable} | Count: {row.cnt} | Range: {row.min_obs} to {row.max_obs}")
except Exception as e:
    print(f"Query failed: {e}")
