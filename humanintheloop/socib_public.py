import requests
import time
from datetime import datetime, timezone

# This public DataDiscovery endpoint does NOT require an API key.
PUBLIC_URL = "https://apps.socib.es/DataDiscovery/list-moorings"
TARGET_PLATFORMS = {
    143: "Bahia de Palma Buoy",
    146: "Canal de Ibiza Buoy",
    512: "Porto Colom Buoy",
    14: "Pollença Station",
}
OBSERVATION_KEYS = {
    143: "bahia_de_palma",
    146: "canal_de_ibiza",
    512: "porto_colom",
    14: "pollensa",
}
TARGET_VARIABLES = {
    "sea_surface_wave_significant_height": "Wave Height",
    "sea_surface_wave_from_direction": "Wave From Direction",
    "sea_water_temperature": "Water Temp",
    "sea_water_practical_salinity": "Salinity",
    "air_pressure": "Air Pressure",
    "air_pressure_at_sea_level": "Sea-level Pressure",
    "wind_speed": "Wind Speed",
    "wind_from_direction": "Wind Direction",
    "wind_speed_of_gust": "Wind Gust",
}
NUMERIC_VARIABLES = {
    "sea_surface_wave_significant_height": "wave_height_m",
    "sea_surface_wave_from_direction": "wave_from_direction_deg",
    "sea_water_temperature": "water_temp_c",
    "sea_water_practical_salinity": "salinity_psu",
    "air_pressure": "air_pressure_hpa",
    "air_pressure_at_sea_level": "sea_level_pressure_hpa",
    "wind_speed": "wind_speed_mps",
    "wind_from_direction": "wind_direction_deg",
    "wind_speed_of_gust": "wind_gust_mps",
}
MAX_OBSERVATION_AGE_HOURS = 48
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 2


def format_timestamp(epoch_seconds):
    if not epoch_seconds:
        return "N/A"
    timestamp = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def observation_age_hours(epoch_seconds, now=None):
    if not epoch_seconds:
        return None
    now = now or datetime.now(timezone.utc)
    timestamp = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return (now - timestamp).total_seconds() / 3600


def is_fresh_observation(epoch_seconds, max_age_hours=MAX_OBSERVATION_AGE_HOURS, now=None):
    age = observation_age_hours(epoch_seconds, now=now)
    return age is not None and 0 <= age <= max_age_hours


def important_values(platform):
    values = []
    for instrument in platform.get("jsonInstrumentList", []):
        for variable in instrument.get("jsonVariableList", []):
            standard_name = variable.get("standardName")
            if standard_name in TARGET_VARIABLES:
                values.append((TARGET_VARIABLES[standard_name], variable.get("lastSampleValue", "N/A")))
    return values


def fetch_public_platforms(
    session=None,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    max_retries=DEFAULT_MAX_RETRIES,
    backoff_seconds=DEFAULT_BACKOFF_SECONDS,
    sleep=time.sleep,
):
    session = session or requests.Session()
    last_error = None
    for attempt in range(max_retries):
        try:
            response = session.get(PUBLIC_URL, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as error:
            last_error = error
            if attempt + 1 >= max_retries:
                raise
            sleep(backoff_seconds * (2**attempt))
    raise last_error


def fetch_public_observations(
    session=None,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    max_retries=DEFAULT_MAX_RETRIES,
    backoff_seconds=DEFAULT_BACKOFF_SECONDS,
    sleep=time.sleep,
    now=None,
):
    try:
        platforms = fetch_public_platforms(
            session=session,
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            sleep=sleep,
        )
    except requests.exceptions.RequestException as error:
        print(f"Warning: SOCIB observations unavailable after {max_retries} attempt(s): {error}")
        return {}
    return extract_public_observations(platforms, now=now)


def get_public_data():
    print("--- Fetching Public SOCIB Data (No Key Required) ---")
    try:
        payload = fetch_public_platforms()
        platforms = {
            platform.get("id"): platform
            for platform in payload
            if platform.get("id") in TARGET_PLATFORMS
        }
        for platform_id, name in TARGET_PLATFORMS.items():
            data = platforms.get(platform_id)
            if not data:
                print(f"{name}: not found in SOCIB DataDiscovery response")
                continue

            print(f"{name}:")
            print(f"  > SOCIB Name: {data.get('name', 'N/A')}")
            print(f"  > Last Sample: {format_timestamp(data.get('lastTimeSampleReceived'))}")
            for label, value in important_values(data):
                    print(f"  > {label}: {value}")
    except Exception as e:
        print(f"Error: {e}")


def extract_public_observations(platforms, now=None):
    observations = {}
    for platform in platforms:
        platform_id = platform.get("id")
        key = OBSERVATION_KEYS.get(platform_id)
        if not key:
            continue

        last_sample = platform.get("lastTimeSampleReceived")
        if not is_fresh_observation(last_sample, now=now):
            continue

        record = {
            "name": platform.get("name", "N/A"),
            "last_sample_utc": format_timestamp(last_sample),
        }
        for instrument in platform.get("jsonInstrumentList", []):
            for variable in instrument.get("jsonVariableList", []):
                output_key = NUMERIC_VARIABLES.get(variable.get("standardName"))
                if output_key:
                    record[output_key] = variable.get("lastValue")
        observations[key] = record
    return observations

if __name__ == "__main__":
    get_public_data()
