#!/usr/bin/env python3
"""
PredSea CMEMS Baseline Ingestor.

Samples the CMEMS 4.2km products PredSea already downloads as CROCO/SWAN driving
forcing -- ``cmems_croco_currents_3d_{region}.nc``, ``cmems_croco_temperature_3d_{region}.nc``,
``cmems_croco_salinity_3d_{region}.nc``, ``cmems_croco_sea_level_{region}.nc``, and
``cmems_swan_boundary_{region}.nc`` under ``gs://{bucket}/forcing/cmems/{run_date}/`` -- at the
same canonical harbor/route points used by scripts/croco_forecast_ingestor.py and
scripts/swan_forecast_ingestor.py, and loads them into BigQuery evidence_rows as
``record_type='forecast'`` rows with ``provider='copernicus'``.

WHY THIS EXISTS: humanintheloop/scripts/model_comparison.py already has the logic to
compare our own model (predsea_croco/predsea_nemo/predsea_swan) against a
"baseline_provider": "copernicus" for every ocean/wave variable in COMPARISON_SPECS, but
nothing was ever writing real 'copernicus'-provider forecast rows into evidence_rows --
so that half of model_comparison.py always reported "no_real_matched_pairs". This script
closes that gap using data the pipeline has already fetched for its own forcing, so no
new CMEMS download or credentials are required.

SCOPE NOTE: this only covers the CMEMS *ocean and wave* baseline (the
"baseline_provider": "copernicus" specs). It deliberately does NOT attempt an ECMWF wind
baseline ("baseline_provider": "ecmwf_open_data") -- that forcing is cached as GRIB2 at
gs://{bucket}/forcing/ecmwf/{run_date}/ecmwf_sfc_{run_date}_*Z.grib2, shared across all
regions rather than region-scoped NetCDF, and needs a GRIB2 reader (cfgrib/eccodes) this
script does not assume is installed. Left as a documented follow-up, not guessed at here.
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

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import numpy as np
import xarray as xr
import pandas as pd
from google.cloud import storage

import place_registry
import route_analysis
from bigquery_export import (
    build_normalized_rows,
    resolve_config,
    authorized_bigquery_session,
    insert_rows,
)

PROVIDER = "copernicus"
NETWORK = "CMEMS_4.2km"

# Each entry: (gcs filename stem, variable-name candidates in the file, [(output_variable,
# units, transform)]). Transform is applied to the raw sampled value(s); for currents it
# needs both u and v so it is handled specially in process_currents().
CMEMS_PRODUCT_STEMS = {
    "currents": "cmems_croco_currents_3d",
    "temperature": "cmems_croco_temperature_3d",
    "salinity": "cmems_croco_salinity_3d",
    "sea_level": "cmems_croco_sea_level",
    "wave": "cmems_swan_boundary",
}

CURRENT_U_NAMES = ("uo", "u", "eastward_sea_water_velocity")
CURRENT_V_NAMES = ("vo", "v", "northward_sea_water_velocity")
TEMPERATURE_NAMES = ("thetao", "temp", "sea_water_temperature")
SALINITY_NAMES = ("so", "salt", "sea_water_salinity")
SEA_LEVEL_NAMES = ("zos", "zeta", "ssh")
WAVE_HEIGHT_NAMES = ("VHM0", "hs", "significant_wave_height")
WAVE_DIRECTION_NAMES = ("VMDR", "dir", "mwd")
WAVE_PERIOD_NAMES = ("VTPK", "tp", "peak_wave_period")


def parse_args(argv=None):
    try:
        from api.config import PREDSEA_GCS_BUCKET, PREDSEA_BIGQUERY_DATASET
    except ImportError:
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"
        PREDSEA_BIGQUERY_DATASET = os.environ.get("PREDSEA_BIGQUERY_DATASET") or f"predsea_validation_{env}"

    parser = argparse.ArgumentParser(
        description="Ingest the CMEMS forcing PredSea already downloads as a 'copernicus' baseline into BigQuery evidence_rows."
    )
    parser.add_argument("--region", required=True, help="Region id, e.g. balearic_1km, alboran_1km (must match simulation/marine/regions/*.json).")
    parser.add_argument("--run-date", required=True, help="ISO run date YYYY-MM-DD whose cached CMEMS forcing to ingest.")
    parser.add_argument("--gcs-bucket", default=PREDSEA_GCS_BUCKET, help="GCS bucket name containing the run's cached forcing.")
    parser.add_argument("--local-dir", help="Override GCS download and read cached CMEMS NetCDFs from this local directory instead.")
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud project).")
    parser.add_argument("--dataset", default=PREDSEA_BIGQUERY_DATASET, help="Target BigQuery dataset.")
    parser.add_argument("--table", default="evidence_rows", help="Target BigQuery table.")
    parser.add_argument("--dry-run", action="store_true", help="Perform extraction and print rows without loading into BigQuery.")
    return parser.parse_args(argv)


def utc_to_local_str(utc_dt: datetime.datetime) -> str:
    try:
        from zoneinfo import ZoneInfo
        return utc_dt.astimezone(ZoneInfo("Europe/Madrid")).strftime("%H:%M")
    except Exception:
        try:
            import pytz
            return utc_dt.astimezone(pytz.timezone("Europe/Madrid")).strftime("%H:%M")
        except Exception:
            return utc_dt.strftime("%H:%M")


def _download_cached_products(bucket_name: str, run_date: str, region: str, dest_dir: Path) -> dict[str, Path]:
    """Downloads whichever of the 5 region-scoped cached CMEMS files exist for this
    run_date. Missing files are skipped (not fatal) -- e.g. a region whose CROCO phase
    never completed may still have a SWAN wave boundary cached, or vice versa."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    found: dict[str, Path] = {}
    for key, stem in CMEMS_PRODUCT_STEMS.items():
        blob_name = f"forcing/cmems/{run_date}/{stem}_{region}.nc"
        blob = bucket.blob(blob_name)
        if not blob.exists():
            print(f"⚠️ Not found: gs://{bucket_name}/{blob_name} -- skipping '{key}'.")
            continue
        local_path = dest_dir / f"{stem}_{region}.nc"
        print(f"📥 Downloading gs://{bucket_name}/{blob_name} -> {local_path}")
        blob.download_to_filename(str(local_path))
        found[key] = local_path
    return found


def _first_existing(dataset: xr.Dataset, names, required: bool = True):
    for name in names:
        if name in dataset:
            return name
    if required:
        raise ValueError(f"Dataset is missing one of required fields: {', '.join(names)}")
    return None


def _lat_lon_names(ds: xr.Dataset):
    lat_name = _first_existing(ds, ("latitude", "lat", "nav_lat"), required=True)
    lon_name = _first_existing(ds, ("longitude", "lon", "nav_lon"), required=True)
    return lat_name, lon_name


def _time_dim(ds: xr.Dataset):
    return next((d for d in ("time", "Time", "time_counter") if d in ds.sizes), None)


def _nearest_grid_indices(lats, lons, target_lat, target_lon):
    cos_lat = np.cos(np.deg2rad(target_lat))
    distance = (lats - target_lat) ** 2 + ((lons - target_lon) * cos_lat) ** 2
    j_idx, i_idx = np.unravel_index(int(np.argmin(distance.values)), distance.shape)
    return int(j_idx), int(i_idx)


def _surface_point_value(variable: xr.DataArray, j_idx: int, i_idx: int, t_idx: int, time_dim: str | None):
    sliced = variable
    if time_dim and time_dim in sliced.dims:
        sliced = sliced.isel({time_dim: t_idx})
    # CMEMS 3-D products carry a "depth" dimension ordered surface-to-bottom; index 0 is
    # the shallowest level, used here as the surface value (same convention already
    # applied to CROCO's own s_rho/level dims in scripts/croco_forecast_ingestor.py).
    for depth_name in ("depth", "elevation", "level"):
        if depth_name in sliced.dims:
            sliced = sliced.isel({depth_name: 0})
    if len(sliced.dims) == 2:
        return float(sliced.values[j_idx, i_idx])
    return float(sliced.values.flat[j_idx * sliced.shape[-1] + i_idx])


def _sampling_targets():
    targets = []
    try:
        for pid in place_registry.available_place_ids():
            pdef = place_registry.place_definition(pid)
            targets.append({
                "id": pid, "name": pdef["name"],
                "latitude": float(pdef["latitude"]), "longitude": float(pdef["longitude"]),
                "route_id": None, "route_name": None,
            })
        print(f"📌 Loaded {len(targets)} canonical harbor locations from registry.")
    except Exception as e:
        print(f"⚠️ Warning: Could not load place registry: {e}")

    try:
        routes = route_analysis.load_routes()
        route_count = 0
        for rid, route in routes.items():
            for idx, pt in enumerate(route_analysis.route_sample_points(route)):
                targets.append({
                    "id": f"{rid}_{idx}", "name": pt["name"],
                    "latitude": float(pt["latitude"]), "longitude": float(pt["longitude"]),
                    "route_id": rid, "route_name": route["name"],
                })
            route_count += 1
        print(f"⛵ Loaded sample points from {route_count} routes.")
    except Exception as e:
        print(f"⚠️ Warning: Could not load routes: {e}")

    return targets


def _time_series(ds: xr.Dataset, time_dim: str | None, run_dt: datetime.datetime, time_size: int):
    """Returns [(t_idx, target_dt, target_time_iso, target_local, lead_hours), ...]."""
    out = []
    for t_idx in range(time_size):
        target_dt = run_dt + datetime.timedelta(hours=t_idx)
        lead_hours = float(t_idx)
        if time_dim and time_dim in ds:
            try:
                time_val = ds[time_dim].values[t_idx]
                target_dt = pd.to_datetime(time_val).to_pydatetime()
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=datetime.timezone.utc)
                lead_hours = (target_dt - run_dt).total_seconds() / 3600.0
            except Exception:
                pass
        out.append((
            t_idx, target_dt,
            target_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            utc_to_local_str(target_dt),
            lead_hours,
        ))
    return out


def _base_row(run_date, run_id, run_dt, target, t):
    t_idx, target_dt, target_time_iso, target_local, lead_hours = t
    return {
        "schema_version": "predsea.validation.v1",
        "record_type": "forecast",
        "source_family": "ocean_forecast",
        "run_date": run_date,
        "run_id": run_id,
        "forecast_created_at_utc": run_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "forecast_source_id": PROVIDER,
        "forecast_source_label": "CMEMS 4.2km baseline (own driving forcing)",
        "ocean_source": PROVIDER,
        "provider": PROVIDER,
        "network": NETWORK,
        "route_id": target["route_id"],
        "route_name": target["route_name"],
        "truth_station_id": target["id"],
        "truth_station_name": target["name"],
        "target_time_utc": target_time_iso,
        "target_local_time": target_local,
        "lead_time_hours": float(lead_hours),
        "resolution_km": 4.2,
        "latitude": target["latitude"],
        "longitude": target["longitude"],
    }


def process_currents(path: Path, run_date, run_id, targets, rows_out):
    with xr.open_dataset(path) as ds:
        lat_name, lon_name = _lat_lon_names(ds)
        u_name = _first_existing(ds, CURRENT_U_NAMES, required=True)
        v_name = _first_existing(ds, CURRENT_V_NAMES, required=True)
        time_dim = _time_dim(ds)
        time_size = ds.sizes.get(time_dim, 1) if time_dim else 1
        lats_grid, lons_grid = ds[lat_name], ds[lon_name]
        if time_dim and time_dim in lats_grid.dims:
            lats_grid = lats_grid.isel({time_dim: 0})
        if time_dim and time_dim in lons_grid.dims:
            lons_grid = lons_grid.isel({time_dim: 0})
        run_dt = datetime.datetime.fromisoformat(run_date).replace(tzinfo=datetime.timezone.utc)
        series = _time_series(ds, time_dim, run_dt, time_size)

        for target in targets:
            j_idx, i_idx = _nearest_grid_indices(lats_grid, lons_grid, target["latitude"], target["longitude"])
            for t in series:
                t_idx = t[0]
                try:
                    u_val = _surface_point_value(ds[u_name], j_idx, i_idx, t_idx, time_dim)
                    v_val = _surface_point_value(ds[v_name], j_idx, i_idx, t_idx, time_dim)
                except Exception as e:
                    continue
                if u_val is None or v_val is None or math.isnan(u_val) or math.isnan(v_val):
                    continue
                speed = math.sqrt(u_val ** 2 + v_val ** 2)
                direction = (math.degrees(math.atan2(-u_val, -v_val)) + 360.0) % 360.0
                base = _base_row(run_date, run_id, run_dt, target, t)
                rows_out.append({**base, "variable": "current_speed", "source_field": f"{u_name}/{v_name}", "value": speed, "units": "m/s"})
                rows_out.append({**base, "variable": "current_direction", "source_field": f"{u_name}/{v_name}", "value": direction, "units": "degree"})


def process_scalar_product(path: Path, run_date, run_id, targets, rows_out, var_names, out_variable, units, transform=None):
    with xr.open_dataset(path) as ds:
        lat_name, lon_name = _lat_lon_names(ds)
        var_name = _first_existing(ds, var_names, required=True)
        time_dim = _time_dim(ds)
        time_size = ds.sizes.get(time_dim, 1) if time_dim else 1
        lats_grid, lons_grid = ds[lat_name], ds[lon_name]
        if time_dim and time_dim in lats_grid.dims:
            lats_grid = lats_grid.isel({time_dim: 0})
        if time_dim and time_dim in lons_grid.dims:
            lons_grid = lons_grid.isel({time_dim: 0})
        run_dt = datetime.datetime.fromisoformat(run_date).replace(tzinfo=datetime.timezone.utc)
        series = _time_series(ds, time_dim, run_dt, time_size)

        for target in targets:
            j_idx, i_idx = _nearest_grid_indices(lats_grid, lons_grid, target["latitude"], target["longitude"])
            for t in series:
                t_idx = t[0]
                try:
                    val = _surface_point_value(ds[var_name], j_idx, i_idx, t_idx, time_dim)
                except Exception:
                    continue
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    continue
                if transform:
                    val = transform(val)
                base = _base_row(run_date, run_id, run_dt, target, t)
                rows_out.append({**base, "variable": out_variable, "source_field": var_name, "value": val, "units": units})


def build_rows(local_files: dict[str, Path], run_date: str, run_id: str) -> list[dict]:
    targets = _sampling_targets()
    rows: list[dict] = []

    if "currents" in local_files:
        print("🌊 Sampling CMEMS currents (uo/vo) baseline...")
        process_currents(local_files["currents"], run_date, run_id, targets, rows)
    if "temperature" in local_files:
        print("🌡️ Sampling CMEMS water temperature baseline...")
        process_scalar_product(
            local_files["temperature"], run_date, run_id, targets, rows,
            TEMPERATURE_NAMES, "water_temperature", "celsius",
            transform=lambda v: v - 273.15 if v > 100.0 else v,
        )
    if "salinity" in local_files:
        print("🧂 Sampling CMEMS salinity baseline...")
        process_scalar_product(local_files["salinity"], run_date, run_id, targets, rows, SALINITY_NAMES, "salinity", "psu")
    if "sea_level" in local_files:
        print("📏 Sampling CMEMS sea level baseline...")
        process_scalar_product(local_files["sea_level"], run_date, run_id, targets, rows, SEA_LEVEL_NAMES, "sea_level", "m")
    if "wave" in local_files:
        print("🌊 Sampling CMEMS wave (VHM0/VMDR/VTPK) baseline...")
        process_scalar_product(local_files["wave"], run_date, run_id, targets, rows, WAVE_HEIGHT_NAMES, "wave_height", "m")
        try:
            process_scalar_product(local_files["wave"], run_date, run_id, targets, rows, WAVE_DIRECTION_NAMES, "wave_direction", "degree")
        except ValueError:
            pass

    return rows


def main(argv=None) -> int:
    args = parse_args(argv)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    run_id = now_utc.strftime("%Y-%m-%dT%H%MZ")

    print("=================================================================")
    print("🚀 PredSea CMEMS Baseline Ingestion Starting")
    print(f"📅 Run Date: {args.run_date}")
    print(f"🗺️ Region: {args.region}")
    print(f"📦 GCS Bucket: {args.gcs_bucket}")
    print(f"🛠️ Dry-run: {args.dry_run}")
    print("=================================================================")

    temp_dir = None
    if args.local_dir:
        source_dir = Path(args.local_dir)
        local_files = {
            key: (source_dir / f"{stem}_{args.region}.nc")
            for key, stem in CMEMS_PRODUCT_STEMS.items()
            if (source_dir / f"{stem}_{args.region}.nc").is_file()
        }
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="cmems_baseline_"))
        local_files = _download_cached_products(args.gcs_bucket, args.run_date, args.region, temp_dir)

    if not local_files:
        print(
            f"❌ No cached CMEMS forcing files found for region={args.region}, run_date={args.run_date} "
            f"under gs://{args.gcs_bucket}/forcing/cmems/{args.run_date}/. Nothing to ingest -- "
            "this is expected if that region's run hasn't reached the CMEMS-fetch step yet."
        )
        return 1

    try:
        raw_rows = build_rows(local_files, args.run_date, run_id)
        print(f"✅ Generated {len(raw_rows)} long-format CMEMS baseline rows.")

        normalized_rows = build_normalized_rows(observation_rows=[], forecast_rows=raw_rows)
        print(f"📊 Standardized and normalized {len(normalized_rows)} rows against target BQ schema.")

        if args.dry_run:
            print(f"⚡ [DRY RUN] Ingestion skipped. Sample formatted row:\n{json.dumps(normalized_rows[0], indent=2, default=str) if normalized_rows else 'None'}")
            return 0

        config = resolve_config(project_id=args.project, dataset_id=args.dataset, table_id=args.table)
        if config is None:
            print("❌ Error: BigQuery configuration resolution failed. Ensure GOOGLE_CLOUD_PROJECT is set. Exiting.")
            return 1

        print(f"📡 Writing rows to BigQuery table: {config.project_id}.{config.dataset_id}.{config.table_id}...")
        session = authorized_bigquery_session()
        result = insert_rows(session, config, normalized_rows)

        if result.get("status") in ("written", "success"):
            print(f"🏆 Ingestion successful! Exported {len(normalized_rows)} CMEMS baseline rows to BigQuery.")
        else:
            print(f"❌ BigQuery Insertion failed: {result.get('error_messages') or result.get('reason')}")
            return 1
    except Exception as e:
        print(f"❌ Ingestion pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if temp_dir is not None:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
