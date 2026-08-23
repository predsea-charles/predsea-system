#!/usr/bin/env python3
"""
PredSea CROCO Forecast Ingestor.
Downloads daily CROCO NetCDF outputs from GCS, samples oceanographic variables
at canonical locations (harbors and route transit coordinates), normalizes them,
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
MPS_TO_KNOTS = 1.9438444924406

ROMS_U_NAMES = ("u", "uo", "u_current", "eastward_sea_water_velocity")
ROMS_V_NAMES = ("v", "vo", "v_current", "northward_sea_water_velocity")
ROMS_TEMP_NAMES = ("temp", "tos", "sst", "temperature_surface", "sea_surface_temperature")
ROMS_SALT_NAMES = ("salt", "sos", "salinity", "sea_surface_salinity")
ROMS_ZETA_NAMES = ("zeta", "zos", "ssh", "sea_surface_height")

PROVIDER = "predsea_croco"
NETWORK = "CROCO_1km"


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
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
    if str(HUMANINTHELOOP_DIR) not in sys.path:
        sys.path.insert(0, str(HUMANINTHELOOP_DIR))

    try:
        from api.config import PREDSEA_GCS_BUCKET, PREDSEA_BIGQUERY_DATASET
    except ImportError:
        import os
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"
        PREDSEA_BIGQUERY_DATASET = os.environ.get("PREDSEA_BIGQUERY_DATASET") or f"predsea_validation_{env}"

    parser = argparse.ArgumentParser(description="Ingest CROCO daily forecasts into BigQuery evidence_rows.")
    parser.add_argument("--run-date", help="ISO run date YYYY-MM-DD. Defaults to UTC today.")
    parser.add_argument("--run-id", help="Run identifier timestamp (defaults to current UTC time).")
    parser.add_argument("--gcs-bucket", default=PREDSEA_GCS_BUCKET, help="GCS bucket name containing simulation runs.")
    parser.add_argument("--local-file", help="Override GCS download and use a local NetCDF file for ingestion.")
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud project).")
    parser.add_argument("--dataset", default=PREDSEA_BIGQUERY_DATASET, help="Target BigQuery dataset.")
    parser.add_argument("--table", default="evidence_rows", help="Target BigQuery table.")
    parser.add_argument("--dry-run", action="store_true", help="Perform extraction and print rows without loading into BigQuery.")
    return parser.parse_args(argv)


def utc_to_local_str(utc_dt: datetime.datetime) -> str:
    """Convert UTC datetime to Europe/Madrid timezone string HH:MM."""
    try:
        from zoneinfo import ZoneInfo
        local_dt = utc_dt.astimezone(ZoneInfo("Europe/Madrid"))
        return local_dt.strftime("%H:%M")
    except Exception:
        try:
            import pytz
            local_dt = utc_dt.astimezone(pytz.timezone("Europe/Madrid"))
            return local_dt.strftime("%H:%M")
        except Exception:
            return utc_dt.strftime("%H:%M")


def download_croco_file_from_gcs(bucket_name: str, run_date: str, run_id: str, local_path: str) -> bool:
    """Find and download the CROCO NetCDF file from GCS daily runs prefix."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    prefix = f"predictions/{run_date}/runs/{run_id}/"
    print(f"🔍 Searching GCS bucket '{bucket_name}' with prefix '{prefix}'...")
    
    blobs = list(bucket.list_blobs(prefix=prefix))
    if not blobs:
        prefix_fallback = f"predictions/{run_date}/"
        print(f"⚠️ No files found in '{prefix}'. Trying fallback prefix '{prefix_fallback}'...")
        blobs = list(bucket.list_blobs(prefix=prefix_fallback))
        
    croco_blobs = candidate_blobs(blobs, "croco")
    selected_blob = download_first_valid(croco_blobs, "croco", local_path)
        
    if selected_blob:
        print(f"📥 Downloading CROCO output: gs://{bucket_name}/{selected_blob.name} -> {local_path}")
        return True
        
    return False


def get_nearest_grid_indices(lats: xr.DataArray, lons: xr.DataArray, target_lat: float, target_lon: float) -> tuple[int, int]:
    """Calculate the grid J, I index closest to target lat/lon using Euclidean distance with lat-cosine correction."""
    cos_lat = np.cos(np.deg2rad(target_lat))
    distance = (lats - target_lat) ** 2 + ((lons - target_lon) * cos_lat) ** 2
    grid_j, grid_i = np.unravel_index(int(np.argmin(distance.values)), distance.shape)
    return int(grid_j), int(grid_i)


def extract_time_slice(variable: xr.DataArray, time_idx: int) -> xr.DataArray:
    """Safe helper to extract the time index slice from a variable."""
    for t_dim in ("Time", "time", "ocean_time", "time_counter"):
        if t_dim in variable.dims:
            return variable.isel({t_dim: time_idx})
    return variable


def get_point_value(variable: xr.DataArray, grid_j: int, grid_i: int, time_idx: int, default: float | None = None) -> float:
    """Safe helper to extract a scalar float value at grid indices, taking surface layer if 3D."""
    sliced = extract_time_slice(variable, time_idx)
    
    # Subset depth if variable is 3D (s_rho, depth, level, etc.)
    for depth_name in ("s_rho", "depth", "depthu", "depthv", "depthw", "z", "level", "s_w"):
        if depth_name in sliced.dims:
            if depth_name == "s_rho":
                sliced = sliced.isel({depth_name: -1})
            else:
                sliced = sliced.isel({depth_name: 0})
                
    try:
        if len(sliced.dims) == 2:
            return float(sliced.values[grid_j, grid_i])
        # Flat fallback
        return float(sliced.values.flat[grid_j * sliced.shape[1] + grid_i])
    except Exception as e:
        if default is not None:
            return default
        raise e


def _first_existing(dataset: xr.Dataset, names: list[str] | tuple[str, ...], required: bool = True) -> str | None:
    for name in names:
        if name in dataset:
            return name
    if required:
        raise ValueError(f"Dataset is missing one of required fields: {', '.join(names)}")
    return None


def process_croco_forecast(
    croco_path: str,
    run_date: str,
    run_id: str,
    bias_map: dict | None = None,
) -> list[dict]:
    """Parse CROCO NetCDF and sample canonical locations and offshore routes."""
    print(f"📖 Opening CROCO dataset: {croco_path}")
    
    with xr.open_dataset(croco_path) as ds:
        # Find coordinates
        lat_name = _first_existing(ds, ("lat_rho", "latitude", "lat", "XLAT", "nav_lat"), required=True)
        lon_name = _first_existing(ds, ("lon_rho", "longitude", "lon", "XLONG", "nav_lon"), required=True)
        
        # Verify required variables
        u_name = _first_existing(ds, ROMS_U_NAMES, required=True)
        v_name = _first_existing(ds, ROMS_V_NAMES, required=True)
        temp_name = _first_existing(ds, ROMS_TEMP_NAMES, required=True)
        salt_name = _first_existing(ds, ROMS_SALT_NAMES, required=True)
        zeta_name = _first_existing(ds, ROMS_ZETA_NAMES, required=True)
        
        # Check time dimension
        time_dim = next((d for d in ("Time", "time", "ocean_time", "time_counter") if d in ds.sizes), None)
        time_size = ds.sizes.get(time_dim, 1) if time_dim else 1
        print(f"⏱️ Dataset contains {time_size} time steps with dimension {time_dim}.")
        
        # Prepare list of places and coordinate tuples to sample
        sampling_targets = []
        
        # 1. Load canonical places from Place Registry
        try:
            place_ids = place_registry.available_place_ids()
            for pid in place_ids:
                pdef = place_registry.place_definition(pid)
                sampling_targets.append({
                    "type": "place",
                    "id": pid,
                    "name": pdef["name"],
                    "latitude": float(pdef["latitude"]),
                    "longitude": float(pdef["longitude"]),
                    "route_id": None,
                    "route_name": None
                })
            print(f"📌 Loaded {len(place_ids)} canonical harbor locations from registry.")
        except Exception as e:
            print(f"⚠️ Warning: Could not load place registry: {e}")
            
        # 2. Load transit routes from Routes Catalog
        try:
            routes = route_analysis.load_routes()
            route_count = 0
            for rid, route in routes.items():
                spoints = route_analysis.route_sample_points(route)
                for idx, pt in enumerate(spoints):
                    sampling_targets.append({
                        "type": "route_point",
                        "id": f"{rid}_{idx}",
                        "name": pt["name"],
                        "latitude": float(pt["latitude"]),
                        "longitude": float(pt["longitude"]),
                        "route_id": rid,
                        "route_name": route["name"]
                    })
                route_count += 1
            print(f"⛵ Loaded sample points from {route_count} routes.")
        except Exception as e:
            print(f"⚠️ Warning: Could not load routes: {e}")
            
        # Standardize coordinates to first time step for search
        lats_grid = extract_time_slice(ds[lat_name], 0)
        lons_grid = extract_time_slice(ds[lon_name], 0)
        
        forecast_rows = []
        run_dt = datetime.datetime.fromisoformat(run_date).replace(tzinfo=datetime.timezone.utc)
        
        # Loop through each time step
        for t_idx in range(time_size):
            # Calculate target time
            lead_hours = t_idx
            target_dt = run_dt + datetime.timedelta(hours=t_idx)
            
            # Extract time coordinate if present and valid
            if time_dim and time_dim in ds:
                try:
                    time_val = ds[time_dim].values[t_idx]
                    target_dt = pd.to_datetime(time_val).to_pydatetime()
                    if target_dt.tzinfo is None:
                        target_dt = target_dt.replace(tzinfo=datetime.timezone.utc)
                    lead_hours = (target_dt - run_dt).total_seconds() / 3600.0
                except Exception:
                    pass
                    
            target_time_iso = target_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            target_local = utc_to_local_str(target_dt)
            
            # Loop through target points
            for target in sampling_targets:
                lat = target["latitude"]
                lon = target["longitude"]
                
                # Get closest grid index
                j_idx, i_idx = get_nearest_grid_indices(lats_grid, lons_grid, lat, lon)
                
                # Extract values
                try:
                    u_val = get_point_value(ds[u_name], j_idx, i_idx, t_idx)
                    v_val = get_point_value(ds[v_name], j_idx, i_idx, t_idx)
                    
                    temp_val = get_point_value(ds[temp_name], j_idx, i_idx, t_idx, default=None) if temp_name else None
                    salt_val = get_point_value(ds[salt_name], j_idx, i_idx, t_idx, default=None) if salt_name else None
                    zeta_val = get_point_value(ds[zeta_name], j_idx, i_idx, t_idx, default=None) if zeta_name else None
                except Exception as e:
                    print(f"⚠️ Error extracting CROCO values at grid ({j_idx}, {i_idx}) for {target['name']}: {e}")
                    continue
                
                # Calculate current speed (m/s) and meteorological direction (degree)
                curr_speed_mps = math.sqrt(u_val**2 + v_val**2)
                curr_dir_deg = (math.degrees(math.atan2(-u_val, -v_val)) + 360.0) % 360.0
                
                variables = [
                    ("current_speed", curr_speed_mps, "m/s", f"{u_name}/{v_name}"),
                    ("current_direction", curr_dir_deg, "degree", f"{u_name}/{v_name}"),
                ]
                
                if temp_val is not None:
                    # Kelvin to Celsius conversion if needed
                    water_temp_c = temp_val - 273.15 if temp_val > 100.0 else temp_val
                    variables.append(("water_temperature", water_temp_c, "celsius", temp_name))
                if salt_val is not None:
                    variables.append(("salinity", salt_val, "psu", salt_name))
                if zeta_val is not None:
                    variables.append(("sea_level", zeta_val, "m", zeta_name))
                    
                for var_name, var_val, var_units, src_field in variables:
                    # Apply real-time bias correction if available
                    corrected_val = var_val
                    if bias_map:
                        bias_key = (target["id"], var_name, target_dt.month, target_dt.hour)
                        if bias_key in bias_map:
                            mean_bias = bias_map[bias_key]
                            corrected_val = var_val - mean_bias
                            if len(forecast_rows) % 1000 == 0:
                                print(f"🔧 Correcting CROCO {var_name} at {target['name']}: {var_val:.2f} -> {corrected_val:.2f} (bias: {mean_bias:.2f})")

                    forecast_rows.append({
                        "schema_version": "predsea.validation.v1",
                        "record_type": "forecast",
                        "source_family": "ocean_forecast",
                        "run_date": run_date,
                        "run_id": run_id,
                        "forecast_created_at_utc": run_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "forecast_source_id": PROVIDER,
                        "forecast_source_label": "PredSea CROCO 1km",
                        "ocean_source": PROVIDER,
                        "provider": PROVIDER,
                        "network": NETWORK,
                        "route_id": target["route_id"],
                        "route_name": target["route_name"],
                        "truth_station_id": target["id"],
                        "truth_station_name": target["name"],
                        "target_time_utc": target_time_iso,
                        "target_local_time": target_local,
                        "variable": var_name,
                        "source_field": src_field,
                        "value": corrected_val,
                        "units": var_units,
                        "lead_time_hours": float(lead_hours),
                        "resolution_km": 1.0,
                        "latitude": lat,
                        "longitude": lon,
                    })

        print(f"✅ Generated {len(forecast_rows)} long-format forecast rows from CROCO outputs.")
        return forecast_rows


def main(argv=None) -> int:
    args = parse_args(argv)
    
    # Calculate times
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    run_date = args.run_date or now_utc.strftime("%Y-%m-%d")
    run_id = args.run_id or now_utc.strftime("%Y-%m-%dT%H%MZ")
    
    print("=================================================================")
    print("🚀 PredSea CROCO Forecast Ingestion Stream Starting")
    print(f"📅 Run Date: {run_date}")
    print(f"🆔 Run ID: {run_id}")
    print(f"📦 GCS Bucket: {args.gcs_bucket}")
    print(f"🛠️ Dry-run: {args.dry_run}")
    print("=================================================================")
    
    temp_nc_path = None
    
    if args.local_file:
        nc_path = args.local_file
        print(f"📂 Utilizing specified local file: {nc_path}")
    else:
        temp_fd, temp_nc_path = tempfile.mkstemp(suffix=".nc")
        os.close(temp_fd)
        nc_path = temp_nc_path
        
        try:
            success = download_croco_file_from_gcs(args.gcs_bucket, run_date, run_id, nc_path)
            if not success:
                if args.dry_run:
                    print("⚠️ [DRY RUN] No CROCO NetCDF outputs could be located in GCS, but continuing dry-run.")
                    return 0
                print(f"❌ Error: No CROCO NetCDF outputs could be located in GCS for {run_date} ({run_id}). Exiting Ingestion.")
                if temp_nc_path and os.path.exists(temp_nc_path):
                    os.unlink(temp_nc_path)
                return 1
        except Exception as e:
            if args.dry_run:
                print(f"⚠️ [DRY RUN] Error downloading CROCO file from GCS: {e}. Continuing dry-run.")
                return 0
            print(f"❌ Error downloading CROCO file from GCS: {e}")
            if temp_nc_path and os.path.exists(temp_nc_path):
                os.unlink(temp_nc_path)
            return 1
            
    try:
        # Load bias map if available
        bias_map = {}
        if not args.dry_run:
            bias_map = load_bias_corrections(args.project, args.dataset, PROVIDER)

        # Extract and format forecast rows
        raw_rows = process_croco_forecast(nc_path, run_date, run_id, bias_map=bias_map)
        
        # Build normalized BigQuery rows using standard helper
        normalized_rows = build_normalized_rows(observation_rows=[], forecast_rows=raw_rows)
        print(f"📊 Standardized and normalized {len(normalized_rows)} rows against target BQ schema.")
        
        if args.dry_run:
            print(f"⚡ [DRY RUN] Ingestion skipped. Sample formatted row:\n{json.dumps(normalized_rows[0], indent=2) if normalized_rows else 'None'}")
            return 0
            
        # Load config and session
        config = resolve_config(
            project_id=args.project,
            dataset_id=args.dataset,
            table_id=args.table
        )
        if config is None:
            print("❌ Error: BigQuery configuration resolution failed. Ensure GOOGLE_CLOUD_PROJECT is set. Exiting.")
            return 1
            
        print(f"📡 Writing rows to BigQuery table: {config.project_id}.{config.dataset_id}.{config.table_id}...")
        session = authorized_bigquery_session()
        result = insert_rows(session, config, normalized_rows)
        
        if result.get("status") in ("written", "success"):
            print(f"🏆 Ingestion successful! Exported {len(normalized_rows)} CROCO forecast rows to BigQuery.")
        else:
            print(f"❌ BigQuery Insertion failed: {result.get('error_messages') or result.get('reason')}")
            return 1
            
    except Exception as e:
        print(f"❌ Ingestion pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if temp_nc_path and os.path.exists(temp_nc_path):
            os.unlink(temp_nc_path)
            
    return 0


if __name__ == "__main__":
    sys.exit(main())
