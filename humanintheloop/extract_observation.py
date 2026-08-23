import os
from google.cloud import bigquery
import pandas as pd

def extract_observations(project_id="predsea-api", dataset_id="predsea_validation", location="europe-west1"):
    """
    Extracts date, lat, lon, variable, and value for all non-null observations.
    """
    client = bigquery.Client(project=project_id, location=location)
    
    # SQL Query with JOIN to get lat/lon from station metadata
    query = f"""
        SELECT 
            CAST(t1.run_date AS STRING) AS date, 
            t2.latitude AS lat, 
            t2.longitude AS lon, 
            t1.variable, 
            t1.value
        FROM 
            `{project_id}.{dataset_id}.evidence_rows` t1
        JOIN 
            `{project_id}.{dataset_id}.station_metadata` t2 
            ON t1.station_id = t2.station_id
        WHERE 
            t1.record_type = 'observation' 
            AND t1.value IS NOT NULL
            AND t2.latitude IS NOT NULL
        ORDER BY 
            t1.run_date DESC
    """
    
    print(f"📡 Querying {dataset_id} for observation data (Project: {project_id})...")
    
    query_job = client.query(query, location=location)
    df = query_job.to_dataframe()
    
    output_file = "extracted_observations.json"
    df.to_json(output_file, orient="records", indent=2)
    
    print(f"✅ Successfully extracted {len(df)} records and saved to {output_file}")
    return df

if __name__ == "__main__":
    extract_observations()
