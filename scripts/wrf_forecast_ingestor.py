#!/usr/bin/env python3
"""
PredSea WRF Forecast Ingestor.
Downloads daily WRF NetCDF outputs from GCS, samples meteorological variables
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
from model_output_discovery import candidate_blobs, download_first_valid, validate_model_output
from bigquery_export import (
    build_normalized_rows,
    resolve_config,
    authorized_bigquery_session,
    insert_rows,
    bigquery_timestamp
)

MPS_TO_KNOTS = 1.9438444924406

PROVIDER = "predsea_wrf"
# The default network for backward compatibility, 
# but we now dynamically set this per domain (WRF_d01, WRF_d03, etc.)
DEFAULT_NETWORK = "WRF_d03"
WRF_PUBLICATION_VARIABLES = (
    "U10",
    "V10",
    "T2",
    "PSFC",
    "SWDOWN",
    "WSPD10MAX",
    "WIND_GUST",
    "gust",
    "XLAT",
    "XLONG",
    "XTIME",
    "Times",
)


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

    parser = argparse.ArgumentParser(description="Ingest WRF daily forecasts into BigQuery evidence_rows.")
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


def download_wrf_files_from_gcs(bucket_name: str, run_date: str, run_id: str, local_dir: Path) -> list[tuple[str, Path]]:
    """Find and download all WRF NetCDF files from GCS daily runs prefix."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    # Try the standard output structure prefix
    prefix = f"predictions/{run_date}/runs/{run_id}/"
    print(f"🔍 Searching GCS bucket '{bucket_name}' with prefix '{prefix}'...")
    
    blobs = list(bucket.list_blobs(prefix=prefix))
    if not blobs:
        # Fallback prefix just in case: predictions/YYYY-MM-DD/
        prefix_fallback = f"predictions/{run_date}/"
        print(f"⚠️ No files found in '{prefix}'. Trying fallback prefix '{prefix_fallback}'...")
        blobs = list(bucket.list_blobs(prefix=prefix_fallback))
        
    wrf_blobs = candidate_blobs(blobs, "wrf")
    domains = {}
    for b in wrf_blobs:
        # Extract domain from filename like wrfout_d03_2026-05-04_00:00:00 or wrf_d03.nc
        import re
        match = re.search(r"d0([1-7])", b.name)
        if match:
            dom_id = f"d0{match.group(1)}"
            domains.setdefault(dom_id, []).append(b)

    downloaded = []
    local_dir.mkdir(parents=True, exist_ok=True)
    
    for dom_id, domain_blobs in domains.items():
        local_path = local_dir / f"wrf_{dom_id}.nc"
        hourly_blobs = [
            blob for blob in domain_blobs
            if Path(blob.name).name.lower().startswith(f"wrfout_{dom_id}_")
        ]
        if hourly_blobs:
            combined_count = download_and_combine_wrf_domain(hourly_blobs, local_path)
            print(
                f"📥 Validated and combined {combined_count} hourly WRF {dom_id} outputs "
                f"from gs://{bucket_name} -> {local_path}"
            )
            downloaded.append((dom_id, local_path))
            continue

        selected = download_first_valid(domain_blobs, "wrf", local_path)
        if selected:
            print(f"📥 Validated WRF {dom_id} output: gs://{bucket_name}/{selected.name} -> {local_path}")
            downloaded.append((dom_id, local_path))
        
    return downloaded


def download_and_combine_wrf_domain(domain_blobs, local_path: Path) -> int:
    """Create a compact chronological WRF series for publication and ingestion.

    Native WRF outputs contain the full 3-D atmospheric state. Loading 25-121
    complete files in a Cloud Run publication job can exhaust memory even
    though the API only needs near-surface meteorology and grid coordinates.
    """
    datasets = []
    with tempfile.TemporaryDirectory(prefix="predsea-wrf-hours-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        for index, blob in enumerate(sorted(domain_blobs, key=lambda item: item.name)):
            hourly_path = temporary_root / f"{index:04d}.nc"
            try:
                blob.download_to_filename(str(hourly_path))
                valid, reason = validate_model_output(hourly_path, "wrf")
                if not valid:
                    raise ValueError(f"Invalid WRF hourly output '{blob.name}': {reason}")
                with xr.open_dataset(hourly_path, decode_times=False) as dataset:
                    selected_variables = [
                        variable for variable in WRF_PUBLICATION_VARIABLES if variable in dataset
                    ]
                    compact = dataset[selected_variables].load()
                    compact.attrs.update(dataset.attrs)
                    datasets.append(compact)
            finally:
                # Native WRF history files contain the complete 3-D state and
                # can be gigabytes each. Retaining 25-121 downloads exhausts
                # Cloud Run ephemeral storage even though the compact surface
                # dataset is small.
                hourly_path.unlink(missing_ok=True)

    if not datasets:
        raise ValueError("No valid WRF hourly outputs were available to combine.")

    combined = xr.concat(
        datasets,
        dim="Time",
        data_vars="minimal",
        coords="minimal",
        compat="override",
        combine_attrs="override",
    )
    try:
        combined.to_netcdf(local_path)
        time_count = int(combined.sizes.get("Time", 0))
    finally:
        combined.close()
        for dataset in datasets:
            dataset.close()

    if time_count != len(datasets):
        raise ValueError(
            f"Combined WRF timeline is incomplete: expected {len(datasets)} timestamps, found {time_count}."
        )
    valid, reason = validate_model_output(local_path, "wrf")
    if not valid:
        raise ValueError(f"Combined WRF output failed validation: {reason}")
    return time_count


def get_nearest_grid_indices(lats: xr.DataArray, lons: xr.DataArray, target_lat: float, target_lon: float) -> tuple[int, int]:
    """Calculate the grid J, I index closest to target lat/lon using Euclidean distance with lat-cosine correction."""
    cos_lat = np.cos(np.deg2rad(target_lat))
    distance = (lats - target_lat) ** 2 + ((lons - target_lon) * cos_lat) ** 2
    grid_j, grid_i = np.unravel_index(int(np.argmin(distance.values)), distance.shape)
    return int(grid_j), int(grid_i)


def extract_time_slice(variable: xr.DataArray, time_idx: int) -> xr.DataArray:
    """Safe helper to extract the time index slice from a variable."""
    if "Time" in variable.dims:
        return variable.isel(Time=time_idx)
    elif "time" in variable.dims:
        return variable.isel(time=time_idx)
    return variable


def get_point_value(variable: xr.DataArray, grid_j: int, grid_i: int, time_idx: int, default: float | None = None) -> float:
    """Safe helper to extract a scalar float value at grid indices."""
    sliced = extract_time_slice(variable, time_idx)
    try:
        if len(sliced.dims) == 2:
            return float(sliced.values[grid_j, grid_i])
        # Flat fallback if dimension names differ
        return float(sliced.values.flat[grid_j * sliced.shape[1] + grid_i])
    except Exception as e:
        if default is not None:
            return default
        raise e


def process_wrf_forecast(
    wrf_path: str,
    run_date: str,
    run_id: str,
    domain_id: str = "d03",
    bias_map: dict | None = None,
) -> list[dict]:
    """Parse WRF NetCDF and sample canonical locations and offshore routes."""
    print(f"📖 Opening WRF dataset for {domain_id}: {wrf_path}")
    network_id = f"WRF_{domain_id}"
    
    with xr.open_dataset(wrf_path) as ds:
        # Verify required coordinates
        if "XLAT" not in ds or "XLONG" not in ds:
            raise ValueError("WRF file is missing XLAT/XLONG grid coordinates.")
        if "U10" not in ds or "V10" not in ds:
            raise ValueError("WRF file is missing wind vector variables U10/V10.")
            
        time_size = ds.sizes.get("Time", 1)
        default_resolution_km = 1.0 if domain_id.startswith("d0") and int(domain_id[2:]) >= 3 else 3.0
        resolution_km = float(ds.attrs.get("DX", default_resolution_km * 1000.0)) / 1000.0
        source_label = f"PredSea {domain_id.upper()} {resolution_km:g}km"
        print(f"⏱️ Dataset contains {time_size} time steps.")
        print(f"🗺️ Native horizontal resolution: {resolution_km:g} km.")
        
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
            
        # Standardize lats/lons to first time step for coordinate distance searches
        lats_grid = extract_time_slice(ds["XLAT"], 0)
        lons_grid = extract_time_slice(ds["XLONG"], 0)
        
        forecast_rows = []
        run_dt = datetime.datetime.fromisoformat(run_date).replace(tzinfo=datetime.timezone.utc)
        
        # Loop through each time step
        for t_idx in range(time_size):
            # Calculate target time
            lead_hours = t_idx
            if "XTIME" in ds:
                xtime_val = ds["XTIME"].values[t_idx]
                target_dt = pd.to_datetime(xtime_val).to_pydatetime()
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=datetime.timezone.utc)
                # Compute exact lead time
                lead_hours = (target_dt - run_dt).total_seconds() / 3600.0
            else:
                target_dt = run_dt + datetime.timedelta(hours=t_idx)
                
            target_time_iso = target_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            target_local = utc_to_local_str(target_dt)
            
            # Loop through each place/route point
            for target in sampling_targets:
                lat = target["latitude"]
                lon = target["longitude"]
                
                # Get closest grid coordinates
                j_idx, i_idx = get_nearest_grid_indices(lats_grid, lons_grid, lat, lon)
                
                # Extract values
                try:
                    u_val = get_point_value(ds["U10"], j_idx, i_idx, t_idx)
                    v_val = get_point_value(ds["V10"], j_idx, i_idx, t_idx)
                    t2_val = get_point_value(ds["T2"], j_idx, i_idx, t_idx, default=288.15)
                    psfc_val = get_point_value(ds["PSFC"], j_idx, i_idx, t_idx, default=101325.0)
                    swdown_val = get_point_value(ds["SWDOWN"], j_idx, i_idx, t_idx, default=0.0) if "SWDOWN" in ds else 0.0
                except Exception as e:
                    print(f"⚠️ Error extracting values at grid ({j_idx}, {i_idx}) for {target['name']}: {e}")
                    continue
                
                # Wind speed and meteorological direction
                wind_speed_mps = math.sqrt(u_val**2 + v_val**2)
                wind_speed_knots = wind_speed_mps * MPS_TO_KNOTS
                wind_dir_deg = (math.degrees(math.atan2(-u_val, -v_val)) + 360.0) % 360.0
                
                # Check for native wind gust, otherwise calculate programmatically
                wind_gust_knots = None
                gust_src_field = None
                for g_var in ("WSPD10MAX", "WIND_GUST", "gust"):
                    if g_var in ds:
                        try:
                            g_val = get_point_value(ds[g_var], j_idx, i_idx, t_idx)
                            wind_gust_knots = g_val * MPS_TO_KNOTS
                            gust_src_field = g_var
                            break
                        except Exception:
                            pass
                if wind_gust_knots is None:
                    wind_gust_knots = wind_speed_knots * 1.3
                    gust_src_field = "U10/V10 calculation"

                # Kelvin to Celsius
                air_temp_c = t2_val - 273.15
                
                # Pa to hPa
                pressure_hpa = psfc_val / 100.0
                
                # Map WRF variables to normalized schemas
                # We group variables into individual rows to match evidence_rows layout
                variables = [
                    ("wind_speed", wind_speed_knots, "knots", "U10/V10"),
                    ("wind_direction", wind_dir_deg, "degree", "U10/V10"),
                    ("wind_gust", wind_gust_knots, "knots", gust_src_field),
                    ("air_temperature", air_temp_c, "celsius", "T2"),
                    ("sea_level_pressure", pressure_hpa, "hPa", "PSFC"),
                ]
                if "SWDOWN" in ds:
                    variables.append(("solar_radiation", swdown_val, "W/m2", "SWDOWN"))
                    
                for var_name, var_val, var_units, src_field in variables:
                    # Apply real-time bias correction if available
                    corrected_val = var_val
                    if bias_map:
                        bias_key = (target["id"], var_name, target_dt.month, target_dt.hour)
                        if bias_key in bias_map:
                            mean_bias = bias_map[bias_key]
                            corrected_val = var_val - mean_bias
                            if len(forecast_rows) % 1000 == 0:
                                print(f"🔧 Correcting WRF {var_name} at {target['name']}: {var_val:.2f} -> {corrected_val:.2f} (bias: {mean_bias:.2f})")

                    forecast_rows.append({
                        "schema_version": "predsea.validation.v1",
                        "record_type": "forecast",
                        "source_family": "atmosphere",  # Override classification to atmosphere
                        "run_date": run_date,
                        "run_id": run_id,
                        "forecast_created_at_utc": run_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "forecast_source_id": PROVIDER,
                        "forecast_source_label": source_label,
                        "ocean_source": PROVIDER,
                        "provider": PROVIDER,
                        "network": network_id,
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
                        "resolution_km": resolution_km,
                        "latitude": lat,
                        "longitude": lon,
                    })
                    
        print(f"✅ Generated {len(forecast_rows)} long-format forecast rows from WRF outputs.")
        return forecast_rows


def main(argv=None) -> int:
    args = parse_args(argv)
    
    # Calculate times
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    run_date = args.run_date or now_utc.strftime("%Y-%m-%d")
    run_id = args.run_id or now_utc.strftime("%Y-%m-%dT%H%MZ")
    
    print("=================================================================")
    print("🚀 PredSea WRF Forecast Ingestion Stream Starting")
    print(f"📅 Run Date: {run_date}")
    print(f"🆔 Run ID: {run_id}")
    print(f"📦 GCS Bucket: {args.gcs_bucket}")
    print(f"🛠️ Dry-run: {args.dry_run}")
    print("=================================================================")
    
    temp_dir_obj = tempfile.TemporaryDirectory()
    temp_dir = Path(temp_dir_obj.name)
    
    try:
        if args.local_file:
            # If local file provided, we assume d03 by default or try to guess
            dom_id = "d03"
            import re
            match = re.search(r"d0([1-7])", args.local_file)
            if match:
                dom_id = f"d0{match.group(1)}"
            wrf_files = [(dom_id, Path(args.local_file))]
            print(f"📂 Utilizing specified local file: {args.local_file} as {dom_id}")
        else:
            wrf_files = download_wrf_files_from_gcs(args.gcs_bucket, run_date, run_id, temp_dir)
            if not wrf_files:
                if args.dry_run:
                    print("⚠️ [DRY RUN] No WRF NetCDF outputs could be located in GCS, but continuing dry-run.")
                    return 0
                print(f"❌ Error: No WRF NetCDF outputs could be located in GCS for {run_date} ({run_id}). Exiting Ingestion.")
                return 1
            
        # Load bias map if available
        bias_map = {}
        if not args.dry_run:
            bias_map = load_bias_corrections(args.project, args.dataset, PROVIDER)

        all_normalized_rows = []
        for dom_id, nc_path in wrf_files:
            try:
                # Extract and format forecast rows for THIS domain
                raw_rows = process_wrf_forecast(str(nc_path), run_date, run_id, domain_id=dom_id, bias_map=bias_map)
                
                # Build normalized BigQuery rows using standard helper
                normalized_rows = build_normalized_rows(observation_rows=[], forecast_rows=raw_rows)
                print(f"📊 {dom_id}: Standardized {len(normalized_rows)} rows.")
                all_normalized_rows.extend(normalized_rows)
            except Exception as e:
                print(f"⚠️ Warning: Failed to process domain {dom_id}: {e}")
                continue
        
        if not all_normalized_rows:
            print("❌ Error: No rows were successfully processed from any domain. Exiting.")
            return 1

        if args.dry_run:
            print(f"⚡ [DRY RUN] Ingestion skipped. Total rows to ingest: {len(all_normalized_rows)}. Sample row:\n{json.dumps(all_normalized_rows[0], indent=2) if all_normalized_rows else 'None'}")
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
            
        print(f"📡 Writing {len(all_normalized_rows)} total rows to BigQuery table: {config.project_id}.{config.dataset_id}.{config.table_id}...")
        session = authorized_bigquery_session()
        result = insert_rows(session, config, all_normalized_rows)
        
        if result.get("status") in ("written", "success"):
            print(f"🏆 Ingestion successful! Exported {len(all_normalized_rows)} total WRF forecast rows to BigQuery.")
        else:
            print(f"❌ BigQuery Insertion failed: {result.get('error_messages') or result.get('reason')}")
            return 1
            
    except Exception as e:
        print(f"❌ Ingestion pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        temp_dir_obj.cleanup()
            
    return 0


if __name__ == "__main__":
    sys.exit(main())
