from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

try:
    import copernicusmarine
    import xarray as xr
except ImportError as e:
    print(f"Warning: Scientific dependencies missing ({e}).")

from api.warnings_service import BIGQUERY_SCOPE, query_bigquery, resolve_env


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingest historical observations directly from Copernicus and EMODnet.")
    parser.add_argument("--project", default=resolve_env("PREDSEA_BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--dataset", default=resolve_env("PREDSEA_BIGQUERY_DATASET", default="predsea_validation"))
    parser.add_argument("--table", default=resolve_env("PREDSEA_BIGQUERY_EVIDENCE_TABLE", default="evidence_rows"))
    parser.add_argument("--gcs-bucket", default="predsea-daily-outputs")
    
    user = os.getenv("COPERNICUSMARINE_SERVICE_USERNAME") or os.getenv("COPERNICUS_MARINE_USER")
    pwd = os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD") or os.getenv("COPERNICUS_MARINE_PASSWORD")
    
    parser.add_argument("--copernicus-user", default=user)
    parser.add_argument("--copernicus-pwd", default=pwd)
    parser.add_argument("--start-date", default=os.getenv("START_DATE", "2019-01-01"))
    parser.add_argument("--end-date", default=os.getenv("END_DATE", "2027-01-01"))
    args = parser.parse_args(argv)

    print(f"🚀 Starting Extraction Pipeline: {args.start_date} to {args.end_date}")

    all_ingested_rows = []

    # 1. COPERNICUS (Sincronizado con tu WAV_ID de olas)
    if args.copernicus_user and args.copernicus_pwd:
        try:
            cop_rows = download_copernicus_data(args)
            all_ingested_rows.extend(cop_rows)
        except Exception as e:
            print(f"❌ Error downloading from Copernicus: {e}")
    else:
        print("⚠️ Skipping Copernicus: Ingestion bypassed due to empty credentials profile.")

    # 2. EMODNET
    try:
        emod_rows = download_emodnet_data(args)
        all_ingested_rows.extend(emod_rows)
    except Exception as e:
        print(f"❌ Error downloading from EMODnet: {e}")

    # 3. SUBIR RESPALDO JSONL A GCS (Para que build_climatology lo vea en la ruta de tu URL)
    if all_ingested_rows:
        upload_jsonl_to_gcs(args, all_ingested_rows)

    return 0

def download_copernicus_data(args) -> list:
    print("📡 Querying Copernicus Marine In-Situ Observations chunk by chunk...")
    dataset_id = "cmems_mod_med_wav_anfc_4.2km_PT1H-i" 
    
    copernicusmarine.login(username=args.copernicus_user, password=args.copernicus_pwd)
    output_filename = "copernicus_temp.nc"
    
    start_dt = pd.to_datetime(args.start_date)
    end_dt = pd.to_datetime(args.end_date)
    
    # Generamos cortes mensuales dinámicos para no saturar la RAM del runner
    date_range = pd.date_range(start=start_dt, end=end_dt, freq="MS")
    
    total_inserted_rows = []
    
    for i in range(len(date_range) - 1):
        chunk_start = date_range[i].strftime("%Y-%m-%dT%H:%M:%S")
        chunk_end = date_range[i+1].strftime("%Y-%m-%dT%H:%M:%S")
        
        print(f"⏳ Downloading Copernicus chunk: {date_range[i].strftime('%Y-%m')}...")
        
        try:
            copernicusmarine.subset(
                dataset_id=dataset_id,
                variables=["VHM0"],
                minimum_longitude=-2.0,
                maximum_longitude=16.0,
                minimum_latitude=35.0,
                maximum_latitude=45.0,
                start_datetime=chunk_start,
                end_datetime=chunk_end,
                output_directory=".",
                output_filename=output_filename,
                file_format="netcdf",
                overwrite=True
            )
            
            if not os.path.exists(output_filename):
                continue

            # Abrimos el NetCDF de forma perezosa (lazy load) con chunks en xarray
            with xr.open_dataset(output_filename, chunks={"time": 100}) as ds:
                df = ds.to_dataframe().reset_index()
            
            rows_to_insert = []
            if "VHM0" in df.columns:
                for _, row in df.dropna(subset=["VHM0"]).iterrows():
                    rows_to_insert.append({
                        "record_type": "observation",
                        "source_system": "copernicus",
                        "source_label": "cmems_mod_med_wav",
                        "station_id": f"grid_{row.get('latitude', 0)}_{row.get('longitude', 0)}",
                        "station_name": "Copernicus Mediterranean Grid Point",
                        "variable": "wave_height",
                        "units": "m",
                        "sample_time_utc": pd.to_datetime(row.get("time")).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "value": float(row["VHM0"]),
                        "status": "validated"
                    })
                
            if rows_to_insert:
                upload_to_bigquery(args, rows_to_insert)
                total_inserted_rows.extend(rows_to_insert)
                print(f"✅ Ingested {len(rows_to_insert)} Copernicus rows for this slice.")
                
        except Exception as chunk_error:
            print(f"⚠️ Copernicus chunk failed or timed out, skipping to next slot: {chunk_error}")
            continue
        finally:
            if os.path.exists(output_filename):
                os.remove(output_filename)
                
    return total_inserted_rows


def download_emodnet_data(args) -> list:
    print("📡 Querying EMODnet Physics Open API (ERDDAP) for Historical Moorings...")
    # Dataset maestro unificado para series históricas de boyas fijas
    base_url = "https://erddap.emodnet-physics.eu/erddap/tabledap/EP_ERD_INT_MO_NRT.csv"
    
    start_year = int(args.start_date.split("-")[0])
    end_year = int(args.end_date.split("-")[0])
    
    # Bounding box covering the entire Western Mediterranean (including Spain, France, and Italy)
    geo_filter = "&latitude>=35.0&latitude<=45.0&longitude>=-2.0&longitude<=16.0"
    
    total_rows = []
    # Usamos end_year + 1 para que el bucle sea totalmente inclusivo con el año en curso
    for year in range(start_year, end_year + 1):
        print(f"⏳ Querying Consolidated Mooring records for year: {year}...")
        
        # Solicitamos tanto temperatura como altura de ola (variables nativas de ERDDAP)
        query_url = (
            f"{base_url}?platform_code,time,latitude,longitude,sea_water_temperature,sea_surface_wave_significant_height"
            f"&time>={year}-01-01T00:00:00Z"
            f"&time<={year}-12-31T23:59:59Z"
            f"{geo_filter}"
        )
        
        try:
            response = requests.get(query_url, timeout=45)
            if response.status_code == 404:
                print(f"ℹ️ No Mooring archives found for year {year} in this bounding box.")
                continue
                
            response.raise_for_status()
            
            from io import StringIO
            csv_data = StringIO(response.text)
            df = pd.read_csv(csv_data, skiprows=[1])
            
            rows_to_insert = []
            for _, row in df.iterrows():
                # Extracción e identificación de Temperatura del Agua
                if pd.notna(row.get("sea_water_temperature")):
                    rows_to_insert.append({
                        "record_type": "observation",
                        "source_system": "emodnet",
                        "source_label": "emodnet_mooring",
                        "station_id": f"emod_{str(row['platform_code'])}",
                        "station_name": f"EMODnet Mooring Bouy {row['platform_code']}",
                        "variable": "water_temperature",
                        "units": "degrees_C",
                        "sample_time_utc": pd.to_datetime(row["time"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "latitude": float(row["latitude"]) if pd.notna(row.get("latitude")) else None,
                        "longitude": float(row["longitude"]) if pd.notna(row.get("longitude")) else None,
                        "value": float(row["sea_water_temperature"]),
                        "status": "validated"
                    })
                
                # Extracción e identificación de Altura de Ola (Mapeado a wave_height de tu MVP)
                if pd.notna(row.get("sea_surface_wave_significant_height")):
                    rows_to_insert.append({
                        "record_type": "observation",
                        "source_system": "emodnet",
                        "source_label": "emodnet_mooring",
                        "station_id": f"emod_{str(row['platform_code'])}",
                        "station_name": f"EMODnet Mooring Bouy {row['platform_code']}",
                        "variable": "wave_height",
                        "units": "m",
                        "sample_time_utc": pd.to_datetime(row["time"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "latitude": float(row["latitude"]) if pd.notna(row.get("latitude")) else None,
                        "longitude": float(row["longitude"]) if pd.notna(row.get("longitude")) else None,
                        "value": float(row["sea_surface_wave_significant_height"]),
                        "status": "validated"
                    })

            if rows_to_insert:
                upload_to_bigquery(args, rows_to_insert)
                total_rows.extend(rows_to_insert)
                print(f"✅ Ingested {len(rows_to_insert)} records for year {year}.")
        except Exception as chunk_error:
            print(f"⚠️ Chunk {year} omitted: {chunk_error}")
            continue
            
    return total_rows


def upload_to_bigquery(args, rows, batch_size=500):
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
    except ImportError as error:
        raise RuntimeError(f"Unable to load Google auth helpers: {error}")

    creds, _ = google.auth.default(scopes=[BIGQUERY_SCOPE])
    session = AuthorizedSession(creds)
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{args.project}/datasets/{args.dataset}/tables/{args.table}/insertAll"
    
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        payload = {
            "skipInvalidRows": False,
            "ignoreUnknownValues": True,
            "rows": [{"json": row} for row in batch],
        }
        response = session.post(url, json=payload)
        response.raise_for_status()


def upload_jsonl_to_gcs(args, rows):
    # --- NUEVA LÓGICA: Sube el JSONL exactamente a la estructura dinámica que compartiste ---
    try:
        from google.cloud import storage
    except ImportError:
        print("GCS library missing. Skipping artifact storage mirror.")
        return

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Emulamos el ID de ejecución con la estampa de tiempo actual del runner
    run_timestamp = datetime.now(timezone.utc).strftime("%H%MZ")
    
    gcs_target_path = f"predictions/{today_str}/runs/{today_str}T{run_timestamp}/validation/observation_samples.jsonl"
    
    local_file = "observation_samples.jsonl"
    with open(local_file, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
            
    try:
        client = storage.Client()
        bucket = client.bucket(args.gcs_bucket)
        blob = bucket.blob(gcs_target_path)
        blob.upload_from_filename(local_file)
        print(f"✨ Canonical artifact mirrored safely to GCS at: gs://{args.gcs_bucket}/{gcs_target_path}")
    except Exception as e:
        print(f"⚠️ GCS upload warning: {e}")
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)


if __name__ == "__main__":
    raise SystemExit(main())
