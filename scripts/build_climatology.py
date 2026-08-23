from __future__ import annotations

import argparse
import json
import math  
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import validation_archive
from api.warnings_service import BIGQUERY_SCOPE, query_bigquery, resolve_env, sql_literal  # noqa: E402


# --- CLIMATOLOGY AGGREGATED BASELINE SCHEMA ---
CLIMATOLOGY_SCHEMA = [
    {"name": "provider", "type": "STRING", "mode": "NULLABLE"},
    {"name": "network", "type": "STRING", "mode": "NULLABLE"},
    {"name": "station_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "station_name", "type": "STRING", "mode": "NULLABLE"},
    {"name": "variable", "type": "STRING", "mode": "REQUIRED"},
    {"name": "month", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "hour_utc", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "clim_mean", "type": "FLOAT", "mode": "REQUIRED"},
    {"name": "clim_stddev", "type": "FLOAT", "mode": "REQUIRED"},
    {"name": "sample_count", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "history_years", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "ingested_at_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
]


def main(argv=None):
    try:
        from api.config import PREDSEA_BIGQUERY_DATASET, PREDSEA_GCS_BUCKET
    except ImportError:
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_BIGQUERY_DATASET = os.environ.get("PREDSEA_BIGQUERY_DATASET") or f"predsea_validation_{env}"
        PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"

    parser = argparse.ArgumentParser(description="Construct climatological baseline aggregated metrics from BigQuery and GCS observations.")
    parser.add_argument("--project", default=resolve_env("PREDSEA_BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--dataset", default=resolve_env("PREDSEA_BIGQUERY_DATASET", "BQ_DATASET", default=PREDSEA_BIGQUERY_DATASET))
    parser.add_argument("--evidence-table", default=resolve_env("PREDSEA_BIGQUERY_EVIDENCE_TABLE", "BQ_TABLE_EVIDENCE", default="evidence_rows"))
    parser.add_argument("--climatology-table", default=resolve_env("PREDSEA_BIGQUERY_CLIMATOLOGY_TABLE", "BQ_TABLE_CLIMATOLOGY", default="climatology_baseline"))
    parser.add_argument("--location", default=resolve_env("PREDSEA_BIGQUERY_LOCATION", "BQ_LOCATION", default="EU"))
    parser.add_argument("--gcs-bucket", default=resolve_env("PREDSEA_CLIMATOLOGY_GCS_BUCKET", default=PREDSEA_GCS_BUCKET))
    parser.add_argument("--gcs-prefix", default=resolve_env("PREDSEA_CLIMATOLOGY_GCS_PREFIX", default="predictions"))
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2025-01-01")
    parser.add_argument("--min-sample-count", type=int, default=30, help="Minimum sample count per cell")
    parser.add_argument("--min-history-years", type=int, default=3, help="Minimum number of unique years in history")
    parser.add_argument("--no-gcs", action="store_true", help="Skip retrieving observations from Google Cloud Storage")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.project:
        raise SystemExit("Missing BigQuery project. Set PREDSEA_BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT.")

    # 1. Recuperar puntos exactos de BigQuery
    query = build_climatology_query(
        project=args.project,
        dataset=args.dataset,
        evidence_table=args.evidence_table,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    try:
        bigquery_rows = query_bigquery(query, project_id=args.project, location=args.location)
    except Exception as error:
        if args.dry_run:
            print(f"Warning: BigQuery query failed ({error}). Using mock data for dry-run.")
            bigquery_rows = []
            for year in [2022, 2023, 2024]:
                for day in range(1, 15):
                    bigquery_rows.append({
                        "provider": "puertos_del_estado",
                        "network": "redmar",
                        "station_id": "palma",
                        "station_name": "Palma",
                        "latitude": 39.57,
                        "longitude": 2.64,
                        "variable": "air_temperature",
                        "unit": "C",
                        "sample_time_utc": f"{year}-06-{day:02d}T08:00:00Z",
                        "value": 24.0 + (day % 3) * 0.5,
                    })
        else:
            raise
    
    # 2. Recuperar puntos exactos de GCS (Copernicus / EMODnet)
    if args.no_gcs:
        print("ℹ️ Skipping GCS observation retrieval (--no-gcs specified).")
        gcs_rows = []
    else:
        try:
            gcs_rows = load_gcs_observation_rows(
                bucket_name=args.gcs_bucket,
                prefix=args.gcs_prefix,
                start_date=args.start_date,
                end_date=args.end_date,
            )
        except Exception as error:
            if args.dry_run:
                print(f"Warning: GCS listing failed ({error}). Continuing dry-run.")
                gcs_rows = []
            else:
                raise
    
    # 3. Combinar y agregar registros para generar el baseline climatológico
    all_raw_rows = [*bigquery_rows, *gcs_rows]
    aggregated_rows = aggregate_climatology_rows(
        all_raw_rows,
        min_sample_count=args.min_sample_count,
        min_history_years=args.min_history_years,
    )
    
    print(
        f"Consolidated {len(all_raw_rows)} raw observations. "
        f"Aggregated into {len(aggregated_rows)} baseline climatology cells (sample_count >= {args.min_sample_count}, history_years >= {args.min_history_years})."
    )

    if args.dry_run:
        return 0

    session = bigquery_session()
    ensure_dataset(session, args.project, args.dataset, args.location)
    ensure_table(session, args.project, args.dataset, args.climatology_table, args.location)
    clear_table(session, args.project, args.dataset, args.climatology_table)
    insert_rows(session, args.project, args.dataset, args.climatology_table, aggregated_rows)
    print("Baseline climatology cells computed and uploaded to baseline layer.")
    return 0


def build_climatology_query(*, project, dataset, evidence_table, start_date, end_date):
    variables = [
        "air_temperature",
        "water_temperature",
        "sea_level",
        "salinity",
        "sea_level_pressure",
    ]
    variable_list = ", ".join(sql_literal(variable) for variable in variables)
    
    # Extrae los campos exactos individuales sin colapsar las filas
    return f"""
SELECT
  source_system AS provider,
  source_label AS network,
  station_id,
  station_name,
  CAST(NULL AS FLOAT64) AS latitude,
  CAST(NULL AS FLOAT64) AS longitude,
  variable,
  units AS unit,
  sample_time_utc,
  value
FROM `{project}.{dataset}.{evidence_table}`
WHERE record_type = 'observation'
  AND variable IN ({variable_list})
  AND sample_time_utc >= TIMESTAMP('{start_date}T00:00:00Z')
  AND sample_time_utc < TIMESTAMP('{end_date}T00:00:00Z')
  AND value IS NOT NULL
"""


def load_gcs_observation_rows(*, bucket_name, prefix, start_date=None, end_date=None, client=None):
    try:
        from google.cloud import storage
    except Exception as error:
        raise RuntimeError(f"Unable to load Google Cloud Storage helpers: {error}") from error

    client = client or storage.Client()
    bucket = client.bucket(bucket_name)
    prefix = (prefix or "").strip("/")
    root_prefix = f"{prefix}/" if prefix else ""
    rows = []
    start_key = _date_key(start_date)
    end_key = _date_key(end_date)

    try:
        blobs = list(client.list_blobs(bucket, prefix=root_prefix))
    except Exception as error:
        # Graceful fallback for dry-runs / permission errors
        print(f"Warning listing blobs on bucket {bucket_name}: {error}")
        return []

    for blob in blobs:
        if not blob.name.endswith(".jsonl"):
            continue
            
        run_date = _run_date_from_blob_name(blob.name, prefix)
        if run_date:
            if start_key and run_date < start_key:
                continue
            if end_key and run_date >= end_key:
                continue
                
        # Enforce rate limiting (30 requests/minute, meaning 2 seconds between external/network operations)
        time.sleep(2)
        try:
            text = blob.download_as_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        except Exception as error:
            print(f"Warning downloading blob {blob.name}: {error}")
            continue
            
    return rows


def process_and_deduplicate_rows(rows):
    deduplicated = {}
    ingested_at = current_timestamp_utc()
    
    for row in rows:
        sample_time = validation_archive.parse_timestamp(
            row.get("sample_time_utc")
            or row.get("observed_at_utc")
            or row.get("source_time_coordinate_utc")
        )
        if sample_time is None:
            continue
            
        value = _as_float(row.get("value"))
        if value is None or math.isnan(value) or math.isinf(value):
            continue
            
        # MAPEO DE ALIAS PARA RECONOCER FUENTES EXTERNAS
        station_id = (
            row.get("station_id") 
            or row.get("station") 
            or row.get("platform_code") 
            or row.get("platform_id")
            or row.get("EDMO_code")
        )
        
        variable = (
            row.get("variable") 
            or row.get("variable_name") 
            or row.get("parameter")
            or row.get("VARIABLE")
        )
        
        if not station_id or not variable:
            continue
            
        provider = row.get("provider") or row.get("source_system") or row.get("source") or "unknown"
        network = row.get("network") or validation_archive.infer_network_from_record(row)
        station_name = row.get("station_name")
        latitude = _as_float(row.get("latitude"))
        longitude = _as_float(row.get("longitude"))
        unit = row.get("unit") or row.get("units")

        if latitude is not None and (math.isnan(latitude) or math.isinf(latitude)):
            latitude = None
        if longitude is not None and (math.isnan(longitude) or math.isinf(longitude)):
            longitude = None

        time_str = format_timestamp(sample_time)
        unique_key = (station_id, variable, time_str)
        
        existing = deduplicated.get(unique_key)
        if existing:
            if existing["latitude"] is None and latitude is not None:
                existing["latitude"] = latitude
            if existing["longitude"] is None and longitude is not None:
                existing["longitude"] = longitude
            if not existing["station_name"] and station_name:
                existing["station_name"] = station_name
            continue

        deduplicated[unique_key] = {
            "provider": provider,
            "network": network,
            "station_id": station_id,
            "station_name": station_name,
            "latitude": latitude,
            "longitude": longitude,
            "variable": variable,
            "unit": unit,
            "sample_time_utc": time_str,
            "value": value,
            "ingested_at_utc": ingested_at,
        }
        
    return sorted(deduplicated.values(), key=lambda x: (x["station_id"], x["variable"], x["sample_time_utc"]))


def aggregate_climatology_rows(rows, min_sample_count=30, min_history_years=3):
    import collections
    normalized_rows = process_and_deduplicate_rows(rows)
    
    # 1. Group by hourly first
    hourly_groups = collections.defaultdict(list)
    for r in normalized_rows:
        try:
            dt = datetime.strptime(r["sample_time_utc"], "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            dt = validation_archive.parse_timestamp(r["sample_time_utc"])
        
        if dt is None:
            continue
            
        month = dt.month
        hour_utc = dt.hour
        year = dt.year
        
        group_key = (r["station_id"], r["variable"], month, hour_utc)
        hourly_groups[group_key].append((r, year, r["value"]))
        
    aggregated = []
    ingested_at = current_timestamp_utc()
    successful_keys = set()
    
    for (station_id, variable, month, hour_utc), items in hourly_groups.items():
        sample_count = len(items)
        if sample_count < min_sample_count:
            continue
            
        years = {year for _, year, _ in items}
        history_years = len(years)
        if history_years < min_history_years:
            continue
            
        values = [val for _, _, val in items]
        mean_val = sum(values) / sample_count
        
        if sample_count > 1:
            variance = sum((x - mean_val) ** 2 for x in values) / (sample_count - 1)
            stddev_val = math.sqrt(variance)
        else:
            stddev_val = 0.0
            
        first_r, _, _ = items[0]
        
        aggregated.append({
            "provider": first_r["provider"],
            "network": first_r["network"],
            "station_id": station_id,
            "station_name": first_r["station_name"],
            "variable": variable,
            "month": month,
            "hour_utc": hour_utc,
            "clim_mean": mean_val,
            "clim_stddev": stddev_val,
            "sample_count": sample_count,
            "history_years": history_years,
            "ingested_at_utc": ingested_at,
        })
        successful_keys.add((station_id, variable, month))
        
    # 2. For any (station_id, variable, month) that has NO successful hourly baselines,
    # try monthly-level aggregation and distribute across 24 hours.
    monthly_groups = collections.defaultdict(list)
    for r in normalized_rows:
        try:
            dt = datetime.strptime(r["sample_time_utc"], "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            dt = validation_archive.parse_timestamp(r["sample_time_utc"])
        
        if dt is None:
            continue
            
        month = dt.month
        year = dt.year
        
        monthly_groups[(r["station_id"], r["variable"], month)].append((r, year, r["value"]))
        
    for (station_id, variable, month), items in monthly_groups.items():
        if (station_id, variable, month) in successful_keys:
            continue
            
        sample_count = len(items)
        if sample_count < min_sample_count:
            continue
            
        years = {year for _, year, _ in items}
        history_years = len(years)
        if history_years < min_history_years:
            continue
            
        values = [val for _, _, val in items]
        mean_val = sum(values) / sample_count
        
        if sample_count > 1:
            variance = sum((x - mean_val) ** 2 for x in values) / (sample_count - 1)
            stddev_val = math.sqrt(variance)
        else:
            stddev_val = 0.0
            
        first_r, _, _ = items[0]
        
        # Distribute monthly aggregate to all 24 hours
        for hour_utc in range(24):
            aggregated.append({
                "provider": first_r["provider"],
                "network": first_r["network"],
                "station_id": station_id,
                "station_name": first_r["station_name"],
                "variable": variable,
                "month": month,
                "hour_utc": hour_utc,
                "clim_mean": mean_val,
                "clim_stddev": stddev_val,
                "sample_count": sample_count,
                "history_years": history_years,
                "ingested_at_utc": ingested_at,
            })
            
    return sorted(aggregated, key=lambda x: (x["station_id"], x["variable"], x["month"], x["hour_utc"]))


def bigquery_session():
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
    except Exception as error:
        raise RuntimeError(f"Unable to load Google auth helpers: {error}") from error

    creds, _ = google.auth.default(scopes=[BIGQUERY_SCOPE])
    return AuthorizedSession(creds)


def ensure_dataset(session, project, dataset, location):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}"
    response = session.get(url)
    if response.status_code == 200:
        return response.json()
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "datasetReference": {"projectId": project, "datasetId": dataset},
        "location": location,
    }
    response = session.post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets", json=payload)
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def ensure_table(session, project, dataset, table, location):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables/{table}"
    response = session.get(url)
    if response.status_code == 200:
        # If the table already exists with the exact telemetry/non-aggregated schema, delete it so we can create the statistical schema table.
        existing_schema = response.json().get("schema", {}).get("fields", [])
        if not any(f["name"] == "clim_mean" for f in existing_schema):
            print("Detected old telemetry/exact schema table. Recreating for climatology baseline aggregated storage...")
            session.delete(url).raise_for_status()
        else:
            return response.json()
            
    payload = {
        "tableReference": {"projectId": project, "datasetId": dataset, "tableId": table},
        "schema": {"fields": CLIMATOLOGY_SCHEMA},
        "clustering": {"fields": ["station_id", "variable"]},
    }
    response = session.post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables", json=payload)
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def clear_table(session, project, dataset, table):
    query = f"TRUNCATE TABLE `{project}.{dataset}.{table}`"
    response = session.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries",
        json={"query": query, "useLegacySql": False, "timeoutMs": 30000},
    )
    if response.status_code not in (200, 201):
        response.raise_for_status()


def insert_rows(session, project, dataset, table, rows, batch_size=500):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables/{table}/insertAll"
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        payload = {
            "skipInvalidRows": False,
            "ignoreUnknownValues": False,
            "rows": [{"insertId": f"{row['station_id']}:{row['variable']}:{row['month']}:{row['hour_utc']}", "json": row} for row in batch],
        }
        response = session.post(url, json=payload)
        response.raise_for_status()


def _run_date_from_blob_name(blob_name, prefix):
    parts = blob_name.split("/")
    if prefix:
        prefix_parts = [part for part in prefix.split("/") if part]
        if parts[: len(prefix_parts)] != prefix_parts:
            return None
        parts = parts[len(prefix_parts) :]
    if len(parts) < 4:
        return None
    return parts[0]


def _date_key(value):
    if not value:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def _as_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def format_timestamp(value):
    if value is None:
        return None
    if hasattr(value, "astimezone"):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def current_timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    raise SystemExit(main())