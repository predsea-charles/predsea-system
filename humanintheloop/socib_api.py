from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import requests


BASE_URL = "https://api.socib.es"
PLATFORM_TYPES = [
    "Coastal Station",
    "Oceanographic Buoy",
    "Sea Level",
    "Weather Station",
]
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 2

STATION_NAME_TO_KEY = {
    "bahia de palma": "bahia_de_palma",
    "bahia de palma buoy": "bahia_de_palma",
    "canal de ibiza": "canal_de_ibiza",
    "canal de ibiza buoy": "canal_de_ibiza",
    "barcelona": "barcelona",
    "barcelona buoy": "barcelona",
    "barcelona station": "barcelona",
    "valencia": "valencia",
    "valencia buoy": "valencia",
    "valencia station": "valencia",
    "soller": "soller",
    "sóller": "soller",
    "port de soller": "soller",
    "port de sóller": "soller",
    "puerto de soller": "soller",
    "port of soller": "soller",
    "pollença": "pollensa",
    "pollensa": "pollensa",
    "porto colom": "porto_colom",
    "portocolom": "porto_colom",
}

VARIABLE_ALIASES = {
    "Hm0 (m)": "wave_height_m",
    "Hmax (m)": "wave_max_m",
    "Tm02 (s)": "wave_period_s",
    "Tp (s)": "peak_period_s",
    "wave_height": "wave_height_m",
    "wave_from_direction": "wave_from_direction_deg",
    "water_temperature": "water_temp_c",
    "wind_speed": "wind_kn",
    "wind_direction": "wind_direction_deg",
    "current_speed": "current_kn",
    "current_direction": "current_direction_deg",
}


def clean_api_key(raw_key):
    if not raw_key:
        return None
    return str(raw_key).strip().replace('"', "").replace("'", "")


def build_headers(api_key=None):
    api_key = clean_api_key(api_key or os.getenv("SOCIB_API_KEY"))
    if not api_key:
        return {}
    return {"apikey": api_key}


def fetch_json(path, params=None, headers=None, timeout=DEFAULT_TIMEOUT_SECONDS, retries=DEFAULT_MAX_RETRIES, backoff_factor=DEFAULT_BACKOFF_FACTOR, session=None, sleep=time.sleep):
    session = session or requests.Session()
    headers = headers or build_headers()
    url = path if path.startswith("http") else f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    last_error = None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            last_error = error
            if attempt + 1 >= retries:
                raise
            sleep(backoff_factor * (2**attempt))
    raise last_error


def fetch_platforms(platform_type=None, api_key=None, **kwargs):
    params = {}
    if platform_type:
        params["platform_type"] = platform_type
    params.setdefault("page_size", 100)
    payload = fetch_json("/platforms/", params=params, headers=build_headers(api_key), **kwargs)
    return unwrap_results(payload)


def fetch_data_sources(platform_id=None, api_key=None, **kwargs):
    params = {"page_size": 100}
    if platform_id is not None:
        params["platform"] = platform_id
    payload = fetch_json("/data-sources/", params=params, headers=build_headers(api_key), **kwargs)
    return unwrap_results(payload)


def fetch_latest_data(data_source_id, api_key=None, **kwargs):
    return fetch_json(
        f"/data-sources/{data_source_id}/data/",
        params={"latest": "true"},
        headers=build_headers(api_key),
        **kwargs,
    )


def fetch_historical_data(data_source_id, initial_datetime, end_datetime, api_key=None, **kwargs):
    return fetch_json(
        f"/data-sources/{data_source_id}/data/",
        params={
            "initial_datetime": initial_datetime,
            "end_datetime": end_datetime,
        },
        headers=build_headers(api_key),
        **kwargs,
    )


def fetch_socib_bundle(dry_run=False, api_key=None, **kwargs):
    headers = build_headers(api_key)
    platforms = []
    data_sources = []
    observations = {}
    errors = {}
    for platform_type in PLATFORM_TYPES:
        try:
            discovered = fetch_platforms(platform_type=platform_type, api_key=api_key, **kwargs)
            platforms.extend(discovered)
            for platform in discovered:
                platform_id = platform.get("id")
                if platform_id is None:
                    continue
                sources = fetch_data_sources(platform_id=platform_id, api_key=api_key, **kwargs)
                data_sources.extend(sources)
                for source in sources:
                    if dry_run:
                        continue
                    source_id = source.get("id")
                    if source_id is None:
                        continue
                    try:
                        payload = fetch_latest_data(source_id, api_key=api_key, **kwargs)
                        record = normalize_socib_payload(payload, platform, source)
                        if record:
                            observations.update(record)
                    except Exception as error:
                        errors[str(source_id)] = str(error)
        except Exception as error:
            errors[platform_type] = str(error)

    return {
        "base_url": BASE_URL,
        "platform_types": PLATFORM_TYPES,
        "platforms": platforms,
        "data_sources": data_sources,
        "observations": observations,
        "observations_lineage": {
            "source": "socib_api",
            "status": "matched_successfully" if observations else "unavailable",
            "platform_types": PLATFORM_TYPES,
        },
        "predictions_lineage": {
            "source": "socib_api",
            "status": "matched_successfully" if data_sources else "unavailable",
        },
        "errors": errors,
    }


def unwrap_results(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    return []


def normalize_socib_payload(payload, platform=None, data_source=None):
    records = {}
    now = datetime.now(timezone.utc)
    for item in unwrap_results(payload):
        if not isinstance(item, dict):
            continue
        station_key = station_key_from_names(
            platform=platform,
            data_source=data_source,
            payload_item=item,
        )
        if not station_key:
            continue
        last_sample_utc = item.get("time") or item.get("timestamp") or item.get("datetime") or item.get("observed_at") or item.get("end_datetime")
        parsed_last_sample = None
        if last_sample_utc is not None:
            try:
                parsed_last_sample = datetime.fromisoformat(str(last_sample_utc).replace("Z", "+00:00"))
            except Exception:
                parsed_last_sample = None
            if parsed_last_sample is not None and parsed_last_sample.tzinfo is None:
                parsed_last_sample = parsed_last_sample.replace(tzinfo=timezone.utc)
        if parsed_last_sample is not None and parsed_last_sample.astimezone(timezone.utc) > now:
            continue
        record = {
            "name": display_name(platform, data_source, item),
            "last_sample_utc": last_sample_utc,
            "sample_time_utc": last_sample_utc,
            "observed_at_utc": last_sample_utc,
            "source_time_coordinate_utc": last_sample_utc,
            "is_future": False,
        }
        for key, value in item.items():
            normalized = VARIABLE_ALIASES.get(str(key).strip()) or VARIABLE_ALIASES.get(str(key).strip().lower())
            if normalized and value is not None:
                record[normalized] = value
        if "wave_height_m" not in record:
            for key in ("wave_height_m", "Hs", "hm0", "hm0_m", "Hm0"):
                if key in item:
                    record["wave_height_m"] = item.get(key)
                    break
        if "wind_kn" not in record:
            for key in ("wind_kn", "wind_speed_kn", "wind_speed", "U10"):
                if key in item:
                    record["wind_kn"] = item.get(key)
                    break
        if "current_kn" not in record:
            for key in ("current_kn", "current_speed_kn", "current_speed", "velocity"):
                if key in item:
                    record["current_kn"] = item.get(key)
                    break
        record["freshness_state"] = "LIVE" if parsed_last_sample is not None else "UNKNOWN"
        records[station_key] = record
    return records


def station_key_from_names(platform=None, data_source=None, payload_item=None):
    candidates = [
        platform_name(platform),
        platform_name(data_source),
        platform_name(payload_item),
        platform_name(payload_item and payload_item.get("name")),
        platform_name(payload_item and payload_item.get("station_name")),
    ]
    for candidate in candidates:
        if candidate and candidate in STATION_NAME_TO_KEY:
            return STATION_NAME_TO_KEY[candidate]
    return None


def platform_name(obj):
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj.strip().lower()
    if isinstance(obj, dict):
        for key in ("name", "station_name", "platform_name", "code", "codigoEstacion"):
            value = obj.get(key)
            if value:
                return str(value).strip().lower()
    return None


def display_name(platform=None, data_source=None, payload_item=None):
    for obj in (platform, data_source, payload_item):
        if not isinstance(obj, dict):
            continue
        for key in ("name", "station_name", "platform_name"):
            value = obj.get(key)
            if value:
                return value
    return "SOCIB source"
