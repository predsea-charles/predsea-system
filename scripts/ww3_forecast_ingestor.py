#!/usr/bin/env python3
"""
PredSea WW3 Wave Forecast Ingestor.
Downloads daily WW3 NetCDF outputs from GCS, samples wave variables (wave height,
period, and direction) at canonical locations and route transit coordinates, normalizes them,
and loads them into BigQuery evidence_rows.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import tempfile
from pathlib import Path

# Setup project import paths
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"

if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

# Lazy-loaded imports
import numpy as np
import xarray as xr
import pandas as pd
from google.cloud import storage

import place_registry
import route_analysis
from model_output_discovery import candidate_blobs, download_first_valid
from bigquery_export import (
    build_normalized_rows,
    resolve_config,
    authorized_bigquery_session,
    insert_rows
)

# Constants
WW3_HS_NAMES = ("hs", "hsign", "significant_wave_height", "swh", "hsig", "Hsign", "Hs")
WW3_TP_NAMES = ("tps", "tp", "peak_wave_period", "tpp", "tpppeak", "RTpeak", "Tp", "fp")
WW3_DIR_NAMES = ("dir", "mwd", "pwd", "wave_direction", "theta0", "mwd_wave", "deg", "Dir")

PROVIDER = "predsea_ww3"
NETWORK = "WW3_1km"


def load_bias_corrections(project_id: str | None, dataset: str, provider: str) -> dict[tuple[str, str, int, int], float]:
    """
    Load all mean bias records from predsea_validation.model_bias for a given provider.
    Returns a dictionary mapping (station_id, variable, month, hour) -> mean_bias.
    """
    from google.cloud import bigquery
    client = bigquery.Client(project=project_id)
    bias_map = {}
    try:
        table_ref = f"{project_id or client.project}.{dataset}.model_bias"
        query = f"""
            SELECT station_id, variable, month, hour, mean_bias
            FROM `{table_ref}`
            WHERE provider = @provider
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("provider", "STRING", provider)
            ]
        )
        print(f"🔍 Fetching bias corrections for provider '{provider}' from BigQuery table `{table_ref}`...")
        query_job = client.query(query, job_config=job_config)
        for row in query_job:
            key = (row.station_id, row.variable, row.month, row.hour)
            bias_map[key] = float(row.mean_bias)
        print(f"✅ Loaded {len(bias_map)} bias correction rules.")
    except Exception as e:
        print(f"⚠️ Warning: Could not load bias corrections (table may not exist yet or no connection): {e}")
    return bias_map


def parse_args(argv=None):
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
    if str(HUMANINTHELOOP_DIR) not in sys.path:
        sys.path.insert(0, str(HUMANINTHELOOP_DIR))

    try:
        from api.config import PREDSEA_GCS_BUCKET, PREDSEA_BIGQUERY_DATASET
    except ImportError:
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"
        PREDSEA_BIGQUERY_DATASET = os.environ.get("PREDSEA_BIGQUERY_DATASET") or f"predsea_validation_{env}"

    parser = argparse.ArgumentParser(description="Ingest daily WW3 Wave Forecast NetCDF to BigQuery")
    parser.add_argument("--run-date", help="Target run date YYYY-MM-DD")
    parser.add_argument("--run-id", help="Target run ID YYYY-MM-DDTHHMMZ")
    parser.add_argument("--gcs-bucket", default=PREDSEA_GCS_BUCKET, help="GCS Bucket")
    parser.add_argument("--dataset-id", default=PREDSEA_BIGQUERY_DATASET, help="BigQuery Dataset")
    parser.add_argument("--dry-run", action="store_true", help="Perform extraction without inserting into BigQuery")
    return parser.parse_args(argv)


def find_variable(dataset: xr.Dataset, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in dataset.data_vars:
            return name
    return None


def extract_ww3_points(nc_path: Path, run_id: str, bias_map: dict | None = None) -> list[dict]:
    ds = xr.open_dataset(nc_path)
    
    hs_var = find_variable(ds, WW3_HS_NAMES)
    tp_var = find_variable(ds, WW3_TP_NAMES)
    dir_var = find_variable(ds, WW3_DIR_NAMES)

    if not hs_var:
        raise ValueError(f"No significant wave height variable found in {nc_path}. Candidates: {WW3_HS_NAMES}")

    # Spatial coords
    lat_name = "latitude" if "latitude" in ds.coords or "latitude" in ds.data_vars else ("lat" if "lat" in ds.coords else None)
    lon_name = "longitude" if "longitude" in ds.coords or "longitude" in ds.data_vars else ("lon" if "lon" in ds.coords else None)

    if not lat_name or not lon_name:
        raise ValueError(f"Could not locate latitude/longitude spatial coordinates in {nc_path}")

    lats = ds[lat_name].values
    lons = ds[lon_name].values

    # Time coord
    time_name = "time" if "time" in ds.coords else ("Times" if "Times" in ds.coords else None)
    if not time_name:
        raise ValueError(f"Could not locate time coordinate in {nc_path}")

    times = ds[time_name].values

    places = place_registry.load_place_registry()
    routes = route_analysis.load_route_definitions()

    sampled_records = []
    
    # 1. Sample at canonical place locations
    for place_id, place_data in places.items():
        plat = place_data.get("latitude")
        plon = place_data.get("longitude")
        if plat is None or plon is None:
            continue

        if lats.ndim == 1 and lons.ndim == 1:
            if plat < lats.min() or plat > lats.max() or plon < lons.min() or plon > lons.max():
                continue
            lat_idx = int(np.abs(lats - plat).argmin())
            lon_idx = int(np.abs(lons - plon).argmin())
            
            for t_idx, t_val in enumerate(times):
                dt_obj = pd.to_datetime(t_val).tz_localize("UTC") if pd.to_datetime(t_val).tzinfo is None else pd.to_datetime(t_val)
                time_str = dt_obj.strftime("%Y-%m-%d %H:%M:%S")

                hs_val = float(ds[hs_var].isel(time=t_idx, latitude=lat_idx, longitude=lon_idx).values)
                if np.isnan(hs_val):
                    continue

                tp_val = float(ds[tp_var].isel(time=t_idx, latitude=lat_idx, longitude=lon_idx).values) if tp_var else None
                dir_val = float(ds[dir_var].isel(time=t_idx, latitude=lat_idx, longitude=lon_idx).values) if dir_var else None

                sampled_records.append({
                    "station_id": place_id,
                    "place_id": place_id,
                    "timestamp": time_str,
                    "wave_height": hs_val,
                    "wave_period": tp_val,
                    "wave_direction": dir_val,
                    "latitude": float(lats[lat_idx]),
                    "longitude": float(lons[lon_idx]),
                })

    ds.close()
    return sampled_records


def main(argv=None):
    args = parse_args(argv)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    run_date = args.run_date or now_utc.strftime("%Y-%m-%d")
    run_id = args.run_id or now_utc.strftime("%Y-%m-%dT%H%MZ")

    print(f"=================================================================")
    print(f"🚀 PredSea WW3 Wave Forecast Ingestion Stream Starting")
    print(f"📅 Run Date: {run_date}")
    print(f"🆔 Run ID: {run_id}")
    print(f"📦 GCS Bucket: {args.gcs_bucket}")
    print(f"🛠️ Dry-run: {args.dry_run}")
    print(f"=================================================================")

    # Discover and download WW3 forecast files from GCS
    storage_client = storage.Client()
    bucket = storage_client.bucket(args.gcs_bucket)

    prefix = f"predictions/{run_date}/runs/{run_id}/"
    print(f"🔍 Searching GCS bucket '{args.gcs_bucket}' with prefix '{prefix}'...")

    blobs = list(bucket.list_blobs(prefix=prefix))
    ww3_blobs = [b for b in blobs if b.name.endswith("ww3_forecast.nc") or "ww3" in b.name.lower()]

    if not ww3_blobs:
        print(f"❌ Error: No WW3 NetCDF outputs could be located in GCS for {run_date} ({run_id}). Exiting Ingestion.")
        sys.exit(1)

    all_sampled = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for blob in ww3_blobs:
            local_nc = tmp_path / Path(blob.name).name
            print(f"📥 Downloading {blob.name} -> {local_nc}...")
            blob.download_to_filename(str(local_nc))
            
            try:
                sampled = extract_ww3_points(local_nc, run_id)
                all_sampled.extend(sampled)
                print(f"  ✅ Extracted {len(sampled)} sampled points from {blob.name}")
            except Exception as e:
                print(f"  ⚠️ Warning: Failed to extract points from {blob.name}: {e}")

    if not all_sampled:
        print("⚠️ Warning: No valid points were extracted from WW3 NetCDF files.")
        sys.exit(0)

    print(f"\n📊 Extracted a total of {len(all_sampled)} WW3 wave forecast records across all regions.")

    if args.dry_run:
        print("⚡ [DRY RUN] Ingestion finished successfully without BigQuery mutation.")
        return

    # Normalize and load to BigQuery
    cfg = resolve_config()
    bq_rows = []
    for rec in all_sampled:
        dt_obj = datetime.datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        
        # Insert wave_height row
        if rec["wave_height"] is not None and not math.isnan(rec["wave_height"]):
            bq_rows.extend(build_normalized_rows(
                provider=PROVIDER,
                station_id=rec["station_id"],
                network=NETWORK,
                latitude=rec["latitude"],
                longitude=rec["longitude"],
                metric="wave_height",
                value=rec["wave_height"],
                unit="m",
                dt_utc=dt_obj,
                run_id=run_id,
            ))

    if bq_rows:
        print(f"🚀 Inserting {len(bq_rows)} normalized evidence rows into BigQuery dataset '{args.dataset_id}'...")
        inserted = insert_rows(bq_rows, dataset_id=args.dataset_id)
        print(f"🎉 BigQuery Ingestion Succeeded! Inserted {inserted} rows.")
    else:
        print("⚠️ No valid rows to insert into BigQuery.")

if __name__ == "__main__":
    main()
