import os
import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import copernicusmarine
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

def is_retryable_error(exception):
    """Check if the error is a transient network or SSL issue."""
    msg = str(exception).lower()
    return any(marker in msg for marker in [
        "ssl", "connection", "timeout", "eof", "503", "502", "504", "429"
    ])

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=20),
    retry=retry_if_exception(is_retryable_error),
    reraise=True
)
def _read_copernicus_dataframe(dataset_id, variables, lon_min, lon_max, lat_min, lat_max, start_time, now):
    """Helper to perform the actual read with retries."""
    return copernicusmarine.read_dataframe(
        dataset_id=dataset_id,
        dataset_part="latest",
        variables=variables,
        minimum_longitude=lon_min,
        maximum_longitude=lon_max,
        minimum_latitude=lat_min,
        maximum_latitude=lat_max,
        start_datetime=start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        end_datetime=now.strftime("%Y-%m-%dT%H:%M:%S"),
    )

def fetch_copernicus_insitu_bundle(dry_run=False, lookback_hours=36):
    """
    Fetches real-time in-situ observations for the entire Western Mediterranean from Copernicus Marine.
    Bounding Box: [35.0, 44.5, -6.0, 15.6]
    Dataset: cmems_obs-ins_med_phybgcwav_mynrt_na_irrlatest
    """
    # 1. Bounding box coordinates for the entire Western Mediterranean (Gibraltar to Messina)
    lat_min, lat_max = 35.0, 44.5
    lon_min, lon_max = -6.0, 15.6

    # 2. Time range (lookback_hours to now)
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=lookback_hours)

    # 3. Handle dry run
    if dry_run:
        return {
            "source": "copernicus_insitu",
            "available": True,
            "observations": {},
            "measurements": {},
            "stations": [],
            "errors": {},
            "lineage": {"source": "copernicus_insitu", "status": "dry_run"}
        }

    observations = {}
    measurements = {}
    stations = {}
    errors = {}

    try:
        # Retrieve credentials
        user = os.getenv("COPERNICUS_USERNAME") or os.getenv("COPERNICUS_MARINE_USER") or "charles.santana"
        pwd = os.getenv("COPERNICUS_PASSWORD") or os.getenv("COPERNICUS_MARINE_PASSWORD")
        if user and pwd:
            copernicusmarine.login(username=user, password=pwd, force_service_selection=True)

        dataset_id = "cmems_obs-ins_med_phybgcwav_mynrt_na_irrlatest"
        variables = [
            "TEMP", "VHM0", "VMDR", "WSPD", "WDIR", 
            "DRYT", "PSAL", "SLEV", "VHM0_SW1", "VMDR_SW1"
        ]

        print(f"📡 Downloading Copernicus In-Situ MED observations from {start_time.isoformat()} to {now.isoformat()}...")
        df = _read_copernicus_dataframe(
            dataset_id=dataset_id,
            variables=variables,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
            start_time=start_time,
            now=now,
        )

        if df is None or df.empty:
            print("⚠️ No observations returned from Copernicus.")
            return {
                "source": "copernicus_insitu",
                "available": False,
                "observations": {},
                "measurements": {},
                "stations": [],
                "errors": {},
                "lineage": {"source": "copernicus_insitu", "status": "empty"}
            }

        # Format rows into canonical records
        for _, row in df.iterrows():
            platform_id = str(row.get("platform_id"))
            if not platform_id or platform_id == "nan":
                continue

            station_id = f"copernicus_insitu_{platform_id.lower()}"
            var_name = row.get("variable")
            val = row.get("value")
            if pd.isna(val):
                continue

            raw_key = None
            variable = None
            units = None

            if var_name == "TEMP":
                raw_key = "water_temp_c"
                variable = "water_temperature"
                units = "celsius"
            elif var_name == "VHM0":
                raw_key = "wave_height_m"
                variable = "wave_height"
                units = "m"
            elif var_name == "VMDR":
                raw_key = "wave_direction_deg"
                variable = "wave_direction"
                units = "degree"
            elif var_name == "WSPD":
                raw_key = "wind_speed_mps"
                variable = "wind_speed"
                units = "m/s"
            elif var_name == "WDIR":
                raw_key = "wind_direction_deg"
                variable = "wind_direction"
                units = "degree"
            elif var_name == "DRYT":
                raw_key = "air_temperature_c"
                variable = "air_temperature"
                units = "celsius"
            elif var_name == "PSAL":
                raw_key = "salinity_psu"
                variable = "salinity"
                units = "psu"
            elif var_name == "SLEV":
                raw_key = "sea_level_m"
                variable = "sea_level"
                units = "m"
            elif var_name == "VHM0_SW1":
                raw_key = "swell_1_height_m"
                variable = "swell_1_height"
                units = "m"
            elif var_name == "VMDR_SW1":
                raw_key = "swell_1_direction_deg"
                variable = "swell_1_direction"
                units = "degree"
            else:
                continue

            # Parse time
            time_str = str(row.get("time"))
            try:
                observed_at = pd.to_datetime(time_str).tz_localize(timezone.utc).isoformat()
            except Exception:
                observed_at = time_str

            latitude = float(row.get("latitude"))
            longitude = float(row.get("longitude"))
            depth = float(row.get("depth")) if not pd.isna(row.get("depth")) else 0.0

            measurement_item = {
                "provider": "copernicus_insitu",
                "source_system": "copernicus_insitu",
                "source_label": "Copernicus In-Situ",
                "network": "copernicus_insitu",
                "station_kind": "platform",
                "station_type": "platform",
                "station_id": station_id,
                "station_name": platform_id,
                "latitude": latitude,
                "longitude": longitude,
                "depth_m": depth,
                "catalog_url": "https://marine.copernicus.eu",
                "dataset_url": "https://marine.copernicus.eu",
                "sample_time_utc": observed_at,
                "observed_at_utc": observed_at,
                "source_time_coordinate_utc": observed_at,
                "freshness_status": "live",
                "freshness_state": "LIVE",
                "quality_score": 1.0,
                "qc_flag": int(row.get("value_qc")) if not pd.isna(row.get("value_qc")) else 1,
                "is_future": False,
                "is_future_timestamp": False,
                "is_qc_good": True,
                "raw_key": raw_key,
                "source_field": var_name,
                "variable": variable,
                "value": float(val),
                "units": units,
            }

            if station_id not in observations:
                observations[station_id] = {
                    "provider": "copernicus_insitu",
                    "source_system": "copernicus_insitu",
                    "source_label": "Copernicus In-Situ",
                    "network": "copernicus_insitu",
                    "station_id": station_id,
                    "station_name": platform_id,
                    "station_kind": "platform",
                    "station_type": "platform",
                    "latitude": latitude,
                    "longitude": longitude,
                    "depth_m": depth,
                    "catalog_url": "https://marine.copernicus.eu",
                    "dataset_url": "https://marine.copernicus.eu",
                    "sample_time_utc": observed_at,
                    "observed_at_utc": observed_at,
                    "source_time_coordinate_utc": observed_at,
                    "freshness_status": "live",
                    "freshness_state": "LIVE",
                    "quality_score": 1.0,
                    "qc_flag": 1,
                    "is_future": False,
                    "is_future_timestamp": False,
                    "is_qc_good": True,
                    "nearest_routes": [],
                    "distance_to_route_nm": None,
                    "measurements": [],
                }
                measurements[station_id] = []

            # Store flat attribute + nested measurements
            observations[station_id][raw_key] = float(val)
            
            # Add knot conversion for wind speed to align with validation_archive schema
            if raw_key == "wind_speed_mps":
                observations[station_id]["wind_speed_kn"] = float(val) * 1.94384

            observations[station_id]["measurements"].append(measurement_item)
            measurements[station_id].append(measurement_item)

            stations[station_id] = {
                "provider": "copernicus_insitu",
                "network": "copernicus_insitu",
                "station_id": station_id,
                "station_name": platform_id,
                "station_kind": "platform",
                "priority": "normal",
                "latitude": latitude,
                "longitude": longitude,
                "depth_m": depth,
                "variables_supported": sorted(list({m["variable"] for m in observations[station_id]["measurements"]})),
                "nearest_routes": [],
                "distance_to_route_nm": None,
                "distance_to_palma": None,
                "distance_to_ibiza": None,
                "distance_to_menorca": None,
                "source_label": "Copernicus In-Situ",
                "catalog_url": "https://marine.copernicus.eu",
                "dataset_url": "https://marine.copernicus.eu",
                "last_sample_utc": observed_at,
            }

        print(f"✅ Successfully loaded {len(observations)} stations from Copernicus In-Situ MED.")

    except Exception as e:
        print(f"❌ Error fetching Copernicus in-situ observations: {e}")
        errors["copernicus_insitu"] = str(e)

    return {
        "source": "copernicus_insitu",
        "available": bool(observations),
        "observations": observations,
        "measurements": measurements,
        "stations": sorted(stations.values(), key=lambda r: r.get("station_name", "")),
        "errors": errors,
        "lineage": {"source": "copernicus_insitu", "status": "completed" if not errors else "error"}
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lookback", type=int, default=36)
    args = parser.parse_args()
    
    res = fetch_copernicus_insitu_bundle(dry_run=args.dry_run, lookback_hours=args.lookback)
    print(f"Fetch Result: Available={res['available']}, Stations={len(res['stations'])}")
