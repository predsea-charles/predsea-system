#!/usr/bin/env python3
"""
PredSea BigQuery Climatology Anomaly Check.
Compares newly ingested observations against the climatology baseline
and registers active warnings to the FastAPI endpoint on Cloud Run.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import requests

BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"

CLIMATOLOGICAL_VARIABLES = {
    "air_temperature": {"label": "Air temperature", "unit": "C"},
    "water_temperature": {"label": "Water temperature", "unit": "C"},
    "sea_level": {"label": "Sea level", "unit": "m"},
    "salinity": {"label": "Salinity", "unit": "PSU"},
    "sea_level_pressure": {"label": "Sea pressure", "unit": "hPa"},
}


def resolve_env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        val = os.environ.get(name)
        if val:
            return val
    return default


def as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def int_value(value) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def query_bigquery_rest(sql: str, project_id: str, location: str = "EU") -> list[dict]:
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
    except ImportError:
        print("❌ Error: 'google-auth' is required to query BigQuery. Run 'pip install google-auth'.", file=sys.stderr)
        sys.exit(1)

    creds, default_project = google.auth.default(scopes=[BIGQUERY_SCOPE])
    project = project_id or default_project
    if not project:
        raise ValueError("Google Cloud Project ID could not be determined.")

    session = AuthorizedSession(creds)
    query_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries"
    payload = {
        "query": sql,
        "useLegacySql": False,
        "timeoutMs": 30000,
        "maxResults": 200,
    }
    if location:
        payload["location"] = location

    print(f"📡 Querying BigQuery project '{project}' (Location: {location})...")
    response = session.post(query_url, json=payload)
    if response.status_code == 400:
        error_msg = response.json().get("error", {}).get("message", response.text)
        raise ValueError(f"BigQuery SQL Error: {error_msg}")
    
    response.raise_for_status()
    body = response.json()

    # Poll if job is not yet completed
    if not body.get("jobComplete", True):
        job_id = (body.get("jobReference") or {}).get("jobId")
        if not job_id:
            return []
        get_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries/{job_id}"
        for _ in range(30):
            time.sleep(1)
            response = session.get(get_url, params={"location": location} if location else None)
            response.raise_for_status()
            body = response.json()
            if body.get("jobComplete", True):
                break

    if body.get("errors"):
        raise RuntimeError(body["errors"][0].get("message") or "BigQuery query failed")

    return parse_rest_response(body)


def parse_rest_response(body: dict) -> list[dict]:
    fields = [field["name"] for field in body.get("schema", {}).get("fields", [])]
    rows = []
    for row_raw in body.get("rows", []):
        row_dict = {}
        for idx, val_entry in enumerate(row_raw.get("f", [])):
            val = val_entry.get("v")
            field_name = fields[idx]
            row_dict[field_name] = val
        rows.append(row_dict)
    return rows


def build_climatology_query(
    project_id: str,
    dataset_id: str,
    table_id: str,
    clim_table: str,
    z_threshold: float,
    lookback_hours: int,
) -> str:
    clim_variables = ", ".join(f"'{var}'" for var in CLIMATOLOGICAL_VARIABLES)
    query = f"""
WITH latest_obs AS (
  SELECT
    variable, station_id, station_name,
    value AS current_value, units,
    sample_time_utc, observed_at_utc, freshness_status,
    latitude, longitude,
    EXTRACT(MONTH FROM sample_time_utc) AS obs_month,
    EXTRACT(HOUR FROM sample_time_utc) AS obs_hour
  FROM `{project_id}.{dataset_id}.{table_id}`
  WHERE record_type = 'observation'
    AND variable IN ({clim_variables})
    AND value IS NOT NULL
    AND ingested_at_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_hours} HOUR)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY variable, station_id
    ORDER BY sample_time_utc DESC
  ) = 1
),
scored AS (
  SELECT
    o.*,
    c.clim_mean,
    c.clim_stddev,
    c.sample_count,
    c.history_years,
    SAFE_DIVIDE(o.current_value - c.clim_mean, c.clim_stddev) AS z_score
  FROM latest_obs o
  JOIN `{project_id}.{dataset_id}.{clim_table}` c
    ON o.station_id = c.station_id
   AND o.variable = c.variable
   AND o.obs_month = c.month
   AND o.obs_hour = c.hour_utc
  WHERE c.sample_count >= 10
    AND c.history_years >= 1
)
SELECT *, 'climatological' AS baseline_type
FROM scored
WHERE z_score >= {z_threshold}
ORDER BY z_score DESC
LIMIT 200
"""
    return query


def generate_warnings(rows: list[dict], generated_at_utc: str) -> list[dict]:
    warnings = []
    for row in rows:
        variable = row.get("variable")
        meta = CLIMATOLOGICAL_VARIABLES.get(variable)
        if not meta:
            continue
        
        value = as_float(row.get("current_value"))
        z_score = as_float(row.get("z_score"))
        if value is None or z_score is None:
            continue
            
        severity = "severe" if z_score >= 2.5 else "moderate" if z_score >= 1.5 else "info"
        station_name = row.get("station_name") or row.get("station_id")
        direction = "above" if z_score >= 0 else "below"
        
        description = (
            f"{station_name}: {meta['label']} is {direction} the climatological "
            f"baseline at {value:.2f} {meta['unit']} (z={z_score:.2f})."
        )
        
        warning = {
            "source": "predsea_anomaly",
            "severity": severity,
            "variable": variable,
            "label": f"{meta['label']} anomaly",
            "description": description,
            "value": value,
            "unit": meta["unit"],
            "z_score": z_score,
            "baseline_type": "climatological",
            "station_id": row.get("station_id"),
            "station_name": row.get("station_name"),
            "latitude": as_float(row.get("latitude")),
            "longitude": as_float(row.get("longitude")),
            "issued_at_utc": generated_at_utc,
            "valid_from_utc": row.get("sample_time_utc"),
            "valid_to_utc": None,
            "route": None,
            "aemet_event": None,
            "aemet_area": None,
            "extra": {
                "baseline_mean": as_float(row.get("clim_mean")),
                "baseline_stddev": as_float(row.get("clim_stddev")),
                "baseline_type": "climatological",
                "clim_month": int_value(row.get("obs_month")),
                "clim_hour_utc": int_value(row.get("obs_hour")),
                "sample_count": int_value(row.get("sample_count")),
                "history_years": int_value(row.get("history_years")),
                "freshness_status": row.get("freshness_status"),
            },
        }
        warnings.append(warning)
    return warnings


def main():
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
    if str(HUMANINTHELOOP_DIR) not in sys.path:
        sys.path.insert(0, str(HUMANINTHELOOP_DIR))

    try:
        from api.config import PREDSEA_BIGQUERY_DATASET
    except ImportError:
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_BIGQUERY_DATASET = os.environ.get("PREDSEA_BIGQUERY_DATASET") or f"predsea_validation_{env}"

    parser = argparse.ArgumentParser(description="Check BigQuery observations against climatology baseline for anomalies.")
    parser.add_argument("--project", help="BigQuery GCP Project ID")
    parser.add_argument("--dataset", default=PREDSEA_BIGQUERY_DATASET, help="BigQuery Dataset ID")
    parser.add_argument("--evidence-table", default="evidence_rows", help="Evidence Rows Table Name")
    parser.add_argument("--climatology-table", default="climatology_baseline", help="Climatology Baseline Table Name")
    parser.add_argument("--location", default="EU", help="BigQuery dataset location")
    parser.add_argument("--z-threshold", type=float, default=1.5, help="Z-score threshold for anomalies (default 1.5)")
    parser.add_argument("--lookback-hours", type=int, default=6, help="Lookback interval for ingestion (default 6 hours)")
    parser.add_argument("--api-url", help="Base URL of the FastAPI application (defaults to PREDSEA_API_URL or http://localhost:8000)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run showing query and mock warning results")
    args = parser.parse_args()

    project_id = args.project or resolve_env("PREDSEA_BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT")
    dataset_id = args.dataset or resolve_env("PREDSEA_BIGQUERY_DATASET", "BQ_DATASET", default=PREDSEA_BIGQUERY_DATASET)
    evidence_table = args.evidence_table or resolve_env("PREDSEA_BIGQUERY_EVIDENCE_TABLE", "BQ_TABLE_EVIDENCE", default="evidence_rows")
    climatology_table = args.climatology_table or resolve_env("PREDSEA_BIGQUERY_CLIMATOLOGY_TABLE", "BQ_TABLE_CLIMATOLOGY", default="climatology_baseline")
    api_url = args.api_url or resolve_env("PREDSEA_API_URL", default="http://localhost:8000").rstrip("/")

    generated_at_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    print("=============================================")
    print("🌊 PredSea Climatology Anomaly Checker Running")
    print(f"📅 Checked At: {generated_at_utc}")
    print(f"🗃️ BQ Target: {project_id}.{dataset_id}.{evidence_table}")
    print(f"📊 Baseline Table: {climatology_table}")
    print(f"📈 Z-Threshold: {args.z_threshold} | Lookback: {args.lookback_hours} hours")
    print(f"🔗 Target API: {api_url}")
    print("=============================================")

    sql = build_climatology_query(
        project_id=project_id or "[PROJECT_ID]",
        dataset_id=dataset_id,
        table_id=evidence_table,
        clim_table=climatology_table,
        z_threshold=args.z_threshold,
        lookback_hours=args.lookback_hours,
    )

    if args.dry_run:
        print("\n⚡ [DRY RUN] Generated BigQuery SQL Query:")
        print(sql)
        print("\n⚡ [DRY RUN] Fabricating a mock warning to test API integration:")
        mock_rows = [
            {
                "variable": "water_temperature",
                "station_id": "emodnet_mock_buoy",
                "station_name": "Balearic Mock Mooring",
                "latitude": "39.5",
                "longitude": "2.5",
                "current_value": "26.8",
                "sample_time_utc": generated_at_utc,
                "freshness_status": "live",
                "obs_month": "6",
                "obs_hour": "12",
                "clim_mean": "21.2",
                "clim_stddev": "2.1",
                "z_score": "2.66",
                "sample_count": "142",
                "history_years": "5",
            }
        ]
        warnings = generate_warnings(mock_rows, generated_at_utc)
        print(f"Generated Warnings: {warnings}")
        try:
            target_endpoint = f"{api_url}/warnings/active"
            print(f"📡 Sending mock warning to {target_endpoint}...")
            res = requests.post(target_endpoint, json=warnings, timeout=10)
            res.raise_for_status()
            print(f"✅ Mock response: {res.json()}")
        except Exception as e:
            print(f"⚠️ Could not push to live API (perhaps server is not running): {e}")
        return

    if not project_id:
        print("❌ Error: No GCP Project ID specified. Please set PREDSEA_BIGQUERY_PROJECT or run with --project.", file=sys.stderr)
        sys.exit(1)

    try:
        rows = query_bigquery_rest(sql, project_id=project_id, location=args.location)
        warnings = generate_warnings(rows, generated_at_utc)
        print(f"🎉 Analysis complete. Found {len(warnings)} climatological anomalies.")
        
        # Post to the API
        target_endpoint = f"{api_url}/warnings/active"
        print(f"📡 Uploading active anomalies to Cloud Run API at {target_endpoint}...")
        res = requests.post(target_endpoint, json=warnings, timeout=15)
        res.raise_for_status()
        print(f"✅ Pushed successfully: {res.json()}")
    except Exception as e:
        print(f"❌ Anomaly check process failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
