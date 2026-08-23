from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

from .common import (
    SOURCE_LABEL,
    SOURCE_SYSTEM,
    is_future_timestamp,
    normalize_text,
    parse_utc_timestamp,
    timestamp_text,
    to_float,
)


ERDDAP_BASE = "https://erddap.emodnet-physics.eu/erddap"
TIMEOUT_SECONDS = 60
LOOKBACK_DAYS = 45

COMMON_COLUMNS = [
    "PLATFORMCODE",
    "SOURCE",
    "SENSOR",
    "time",
    "TIME_QC",
    "depth",
    "DEPTH_QC",
    "latitude",
    "longitude",
    "POSITION_QC",
]

DATASET_SPECS = (
    {
        "dataset_id": "ERD_EP_TS_VTDH_NRT",
        "title": "significant wave height",
        "measurements": (
            {"column": "VTDH", "raw_key": "wave_height_m", "variable": "wave_height", "units": "m"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_VGHS_NRT",
        "title": "generic significant wave height",
        "measurements": (
            {"column": "VGHS", "raw_key": "wave_height_m", "variable": "wave_height", "units": "m"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_VAVH_NRT",
        "title": "average height of highest 1/3 wave",
        "measurements": (
            {"column": "VAVH", "raw_key": "wave_height_m", "variable": "wave_height", "units": "m"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_VTPK_NRT",
        "title": "wave period at spectral peak",
        "measurements": (
            {"column": "VTPK", "raw_key": "wave_period_peak_s", "variable": "wave_period_peak", "units": "s"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_VTM02_NRT",
        "title": "spectral moments wave period",
        "measurements": (
            {"column": "VTM02", "raw_key": "wave_period_mean_s", "variable": "wave_period_mean", "units": "s"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_VDIR_NRT",
        "title": "wave direction relative to true north",
        "measurements": (
            {"column": "VDIR", "raw_key": "wave_direction_deg", "variable": "wave_direction", "units": "degree"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_VMDR_NRT",
        "title": "mean wave direction",
        "measurements": (
            {"column": "VMDR", "raw_key": "wave_direction_deg", "variable": "wave_direction", "units": "degree"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_WDIR_WSPD_NRT",
        "title": "wind direction and wind speed",
        "measurements": (
            {"column": "WSPD", "raw_key": "wind_speed_mps", "variable": "wind_speed", "units": "m/s"},
            {"column": "WDIR", "raw_key": "wind_direction_deg", "variable": "wind_direction", "units": "degree"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_GSPD_NRT",
        "title": "gust wind speed",
        "measurements": (
            {"column": "GSPD", "raw_key": "wind_speed_mps", "variable": "wind_speed", "units": "m/s"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_HCDT_HCSP_NRT",
        "title": "current direction and current speed",
        "measurements": (
            {"column": "HCSP", "raw_key": "current_speed_mps", "variable": "current_speed", "units": "m/s"},
            {"column": "HCDT", "raw_key": "current_direction_deg", "variable": "current_direction", "units": "degree"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_EWCT_NSCT_NRT",
        "title": "east-west and north-south current components",
        "measurements": (
            {"column": "EWCT", "raw_key": "current_u_mps", "variable": "current_u", "units": "m/s"},
            {"column": "NSCT", "raw_key": "current_v_mps", "variable": "current_v", "units": "m/s"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_TEMP_NRT",
        "title": "sea temperature",
        "measurements": (
            {"column": "TEMP", "raw_key": "water_temp_c", "variable": "water_temperature", "units": "celsius"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_PSAL_NRT",
        "title": "practical salinity",
        "measurements": (
            {"column": "PSAL", "raw_key": "salinity_psu", "variable": "salinity", "units": "psu"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_PSAL_TEMP_NRT",
        "title": "sea temperature and practical salinity",
        "measurements": (
            {"column": "TEMP", "raw_key": "water_temp_c", "variable": "water_temperature", "units": "celsius"},
            {"column": "PSAL", "raw_key": "salinity_psu", "variable": "salinity", "units": "psu"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_SLEV_NRT_5m",
        "title": "water surface height 5 minutes",
        "measurements": (
            {"column": "SLEV", "raw_key": "sea_level_m", "variable": "sea_level", "units": "m"},
        ),
    },
    {
        "dataset_id": "ERD_EP_TS_SLEV_NRT_60m",
        "title": "water surface height 60 minutes",
        "measurements": (
            {"column": "SLEV", "raw_key": "sea_level_m", "variable": "sea_level", "units": "m"},
        ),
    },
)


def _now_utc():
    return datetime.now(timezone.utc)


def _station_id(platform_code, dataset_id):
    base = normalize_text(platform_code)
    if not base:
        base = normalize_text(dataset_id)
    return f"emodnet_{base}"


def _clean_text(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _freshness_status(observed_at_utc, reference_utc=None):
    observed = parse_utc_timestamp(observed_at_utc)
    reference = parse_utc_timestamp(reference_utc) if reference_utc is not None else _now_utc()
    if observed is None or reference is None:
        return "unknown"
    if observed > reference + timedelta(minutes=5):
        return "future"
    age = reference - observed
    if age <= timedelta(hours=2):
        return "live"
    if age <= timedelta(hours=6):
        return "recent"
    if age <= timedelta(hours=12):
        return "aging"
    if age <= timedelta(hours=24):
        return "stale"
    return "stale"


def _quality_score(qc_flag):
    if qc_flag is None:
        return None
    try:
        qc = int(qc_flag)
    except Exception:
        return None
    if qc in {0, 1, 2}:
        return 1.0
    return 0.0


def _build_query_url(dataset_id, columns, *, order_by_max=True):
    column_text = ",".join(columns)
    query = f"{ERDDAP_BASE}/tabledap/{dataset_id}.csv?{column_text}"
    if order_by_max:
        query += f"&orderByMax(%22PLATFORMCODE,time%22)"
    return query


def _dataset_rows(dataset_id, columns, *, session=None, timeout=TIMEOUT_SECONDS, max_retries=2, backoff_seconds=2):
    query_url = _build_query_url(dataset_id, columns)
    session = session or requests.Session()
    last_error = None
    for attempt in range(max_retries):
        try:
            response = session.get(query_url, timeout=timeout)
            response.raise_for_status()
            frame = pd.read_csv(io.StringIO(response.text), skiprows=[1])
            return frame, query_url
        except Exception as error:
            last_error = error
            message = str(error).lower()
            if "no matching results" in message or "not found" in message:
                return pd.DataFrame(), query_url
            if attempt >= max_retries - 1:
                raise
            # backoff is intentionally light; these are public service calls.
            import time

            time.sleep(backoff_seconds * (2 ** attempt))
    raise last_error


def _station_record_from_row(dataset_id, row, *, query_url):
    platform_code = _clean_text(row.get("PLATFORMCODE")) or dataset_id
    station_id = _station_id(platform_code, dataset_id)
    observed_at = timestamp_text(row.get("time"))
    latitude = to_float(row.get("latitude"))
    longitude = to_float(row.get("longitude"))
    source_time_coordinate_utc = observed_at
    freshness_status = _freshness_status(observed_at)
    future_flag = freshness_status == "future"

    record = {
        "provider": "emodnet_physics",
        "source_system": SOURCE_SYSTEM,
        "source_label": SOURCE_LABEL,
        "network": "emodnet_physics",
        "station_id": station_id,
        "station_name": platform_code or dataset_id,
        "station_kind": "platform",
        "station_type": "platform",
        "latitude": latitude,
        "longitude": longitude,
        "depth_m": to_float(row.get("depth")),
        "catalog_url": _clean_text(row.get("url_metadata")) or f"{ERDDAP_BASE}/info/{dataset_id}/index.html",
        "dataset_url": query_url,
        "sample_time_utc": observed_at,
        "observed_at_utc": observed_at,
        "source_time_coordinate_utc": source_time_coordinate_utc,
        "freshness_status": freshness_status,
        "freshness_state": freshness_status.upper(),
        "quality_score": None,
        "qc_flag": None,
        "is_future": future_flag,
        "is_future_timestamp": future_flag,
        "is_qc_good": None,
        "nearest_routes": [],
        "distance_to_route_nm": None,
        "measurements": [],
    }
    return record


def _measurement_from_row(row, measurement_spec, *, query_url):
    value = row.get(measurement_spec["column"])
    if pd.isna(value):
        return None
    qc_column = f"{measurement_spec['column']}_QC"
    qc_flag = row.get(qc_column)
    qc_value = None
    if qc_flag is not None and not pd.isna(qc_flag):
        try:
            qc_value = int(qc_flag)
        except Exception:
            qc_value = None
    observed_at = timestamp_text(row.get("time"))
    freshness_status = _freshness_status(observed_at)
    return {
        "provider": "emodnet_physics",
        "source_system": SOURCE_SYSTEM,
        "source_label": SOURCE_LABEL,
        "network": "emodnet_physics",
        "station_kind": "platform",
        "station_type": "platform",
        "station_id": None,  # filled by caller
        "station_name": None,  # filled by caller
        "latitude": to_float(row.get("latitude")),
        "longitude": to_float(row.get("longitude")),
        "depth_m": to_float(row.get("depth")),
        "catalog_url": _clean_text(row.get("url_metadata")) or f"{ERDDAP_BASE}/info/{query_url.split('/tabledap/')[1].split('.csv?')[0]}/index.html",
        "dataset_url": query_url,
        "sample_time_utc": observed_at,
        "observed_at_utc": observed_at,
        "source_time_coordinate_utc": observed_at,
        "freshness_status": freshness_status,
        "freshness_state": freshness_status.upper(),
        "quality_score": _quality_score(qc_value),
        "qc_flag": qc_value,
        "is_future": freshness_status == "future",
        "is_future_timestamp": freshness_status == "future",
        "is_qc_good": qc_value in {0, 1, 2} if qc_value is not None else None,
        "raw_key": measurement_spec["raw_key"],
        "source_field": measurement_spec["column"],
        "variable": measurement_spec["variable"],
        "value": to_float(value),
        "units": measurement_spec["units"],
    }


def parse_dataset_frame(dataset_id, frame, *, query_url):
    if frame is None or frame.empty:
        return {
            "observations": {},
            "measurements": {},
            "stations": [],
        }

    # Filter by Mediterranean coordinate bounding region (Spain, France, Italy, Greece)
    # Latitude: 30.0 to 46.0, Longitude: -10.0 to 30.0
    if "latitude" in frame.columns and "longitude" in frame.columns:
        lat_col = pd.to_numeric(frame["latitude"], errors="coerce")
        lon_col = pd.to_numeric(frame["longitude"], errors="coerce")
        frame = frame[
            (lat_col >= 30.0) & (lat_col <= 46.0) &
            (lon_col >= -10.0) & (lon_col <= 30.0)
        ]

    if frame.empty:
        return {
            "observations": {},
            "measurements": {},
            "stations": [],
        }

    spec = next(item for item in DATASET_SPECS if item["dataset_id"] == dataset_id)
    observations = {}
    measurements = {}
    stations = {}

    for _, row in frame.iterrows():
        record = _station_record_from_row(dataset_id, row, query_url=query_url)
        station_id = record["station_id"]
        station_measurements = []
        for measurement_spec in spec["measurements"]:
            measurement = _measurement_from_row(row, measurement_spec, query_url=query_url)
            if measurement is None:
                continue
            measurement["station_id"] = station_id
            measurement["station_name"] = record["station_name"]
            station_measurements.append(measurement)
        if not station_measurements:
            continue
        record["measurements"] = station_measurements
        existing = observations.get(station_id)
        if existing is None:
            observations[station_id] = record
            measurements[station_id] = list(station_measurements)
        else:
            existing_measurements = existing.setdefault("measurements", [])
            existing_measurements.extend(station_measurements)
            existing["is_future"] = existing.get("is_future") or record.get("is_future")
            existing["is_future_timestamp"] = existing.get("is_future_timestamp") or record.get("is_future_timestamp")
            existing["freshness_status"] = _preferred_freshness(existing.get("freshness_status"), record.get("freshness_status"))
            existing["freshness_state"] = existing["freshness_status"].upper()
            existing["observed_at_utc"] = _latest_timestamp(existing.get("observed_at_utc"), record.get("observed_at_utc"))
            existing["sample_time_utc"] = existing["observed_at_utc"]
            existing["source_time_coordinate_utc"] = existing["observed_at_utc"]
            existing["quality_score"] = max(
                [score for score in [existing.get("quality_score"), record.get("quality_score")] if score is not None],
                default=None,
            )
            existing["latitude"] = existing.get("latitude") if existing.get("latitude") is not None else record.get("latitude")
            existing["longitude"] = existing.get("longitude") if existing.get("longitude") is not None else record.get("longitude")
            existing["dataset_url"] = existing.get("dataset_url") or record.get("dataset_url")
            existing["catalog_url"] = existing.get("catalog_url") or record.get("catalog_url")
            measurements[station_id].extend(station_measurements)
        stations[station_id] = {
            "provider": record["provider"],
            "network": record["network"],
            "station_id": station_id,
            "station_name": record["station_name"],
            "station_kind": record["station_kind"],
            "priority": "normal",
            "latitude": record["latitude"],
            "longitude": record["longitude"],
            "depth_m": record["depth_m"],
            "variables_supported": sorted({m["variable"] for m in observations[station_id]["measurements"]}),
            "nearest_routes": [],
            "distance_to_route_nm": None,
            "distance_to_palma": None,
            "distance_to_ibiza": None,
            "distance_to_menorca": None,
            "source_label": SOURCE_LABEL,
            "catalog_url": record["catalog_url"],
            "dataset_url": record["dataset_url"],
            "last_sample_utc": observations[station_id].get("observed_at_utc"),
        }

    return {
        "observations": observations,
        "measurements": measurements,
        "stations": sorted(
            stations.values(),
            key=lambda row: (row.get("station_name") or "", row.get("station_id") or ""),
        ),
    }


def _merge_observation_records(existing, incoming):
    merged = dict(existing)
    existing_measurements = list(existing.get("measurements") or [])
    incoming_measurements = list(incoming.get("measurements") or [])
    merged_measurements = existing_measurements + incoming_measurements
    merged["measurements"] = merged_measurements
    merged["is_future"] = bool(existing.get("is_future") or incoming.get("is_future"))
    merged["is_future_timestamp"] = bool(existing.get("is_future_timestamp") or incoming.get("is_future_timestamp"))
    merged["freshness_status"] = _preferred_freshness(existing.get("freshness_status"), incoming.get("freshness_status"))
    merged["freshness_state"] = (merged["freshness_status"] or "unknown").upper()
    merged["observed_at_utc"] = _latest_timestamp(existing.get("observed_at_utc"), incoming.get("observed_at_utc"))
    merged["sample_time_utc"] = merged["observed_at_utc"]
    merged["source_time_coordinate_utc"] = merged["observed_at_utc"]
    merged["quality_score"] = max(
        [score for score in [existing.get("quality_score"), incoming.get("quality_score")] if score is not None],
        default=None,
    )
    if merged.get("latitude") is None:
        merged["latitude"] = incoming.get("latitude")
    if merged.get("longitude") is None:
        merged["longitude"] = incoming.get("longitude")
    merged["catalog_url"] = merged.get("catalog_url") or incoming.get("catalog_url")
    merged["dataset_url"] = merged.get("dataset_url") or incoming.get("dataset_url")
    return merged


def _preferred_freshness(current, candidate):
    order = {"future": 0, "live": 1, "recent": 2, "aging": 3, "stale": 4, "unknown": 5, None: 6}
    current_value = order.get(str(current).lower() if current else current, 6)
    candidate_value = order.get(str(candidate).lower() if candidate else candidate, 6)
    return candidate if candidate_value <= current_value else current


def _latest_timestamp(current, candidate):
    current_dt = parse_utc_timestamp(current)
    candidate_dt = parse_utc_timestamp(candidate)
    if current_dt is None:
        return timestamp_text(candidate)
    if candidate_dt is None:
        return timestamp_text(current)
    return timestamp_text(max(current_dt, candidate_dt))


def fetch_emodnet_observations(
    *,
    dry_run=False,
    timeout=TIMEOUT_SECONDS,
    max_retries=2,
    backoff_seconds=2,
    session=None,
):
    if dry_run:
        return {
            "observations": {},
            "measurements": {},
            "lineage": {
                "source": "emodnet_physics",
                "status": "unavailable",
                "stations_matched": 0,
                "station_ids": [],
                "source_labels": [],
            },
            "errors": {},
            "source": "emodnet_physics",
            "catalog_count": 0,
            "catalog_stations": [],
            "cache_paths": [],
            "network_ids": ["ERDDAP"],
        }

    observations = {}
    measurements = {}
    stations = []
    errors = {}
    source_labels = set()
    session = session or requests.Session()

    for spec in DATASET_SPECS:
        dataset_id = spec["dataset_id"]
        columns = list(COMMON_COLUMNS)
        for measurement_spec in spec["measurements"]:
            columns.append(measurement_spec["column"])
            columns.append(f"{measurement_spec['column']}_QC")
            columns.append(f"{measurement_spec['column']}_DM")
        # Keep columns unique and stable.
        columns = list(dict.fromkeys(columns))
        try:
            frame, query_url = _dataset_rows(
                dataset_id,
                columns,
                session=session,
                timeout=timeout,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
            )
            parsed = parse_dataset_frame(dataset_id, frame, query_url=query_url)
        except Exception as error:  # pragma: no cover - network path
            errors[dataset_id] = str(error)
            continue

        parsed_observations = parsed.get("observations", {})
        for station_id, record in parsed_observations.items():
            if station_id in observations:
                observations[station_id] = _merge_observation_records(observations[station_id], record)
            else:
                observations[station_id] = record
        parsed_measurements = parsed.get("measurements", {})
        for station_id, items in parsed_measurements.items():
            measurements.setdefault(station_id, []).extend(items)
        stations_by_id = {station.get("station_id"): station for station in stations}
        for station in parsed.get("stations", []):
            station_id = station.get("station_id")
            if not station_id:
                continue
            existing_station = stations_by_id.get(station_id)
            if existing_station is None:
                stations.append(station)
                stations_by_id[station_id] = station
            else:
                existing_station.update(station)
        if parsed.get("observations"):
            source_labels.add(SOURCE_LABEL)

    station_ids = sorted(observations.keys())
    lineage = {
        "source": "emodnet_physics",
        "status": "matched_successfully" if observations else "unavailable",
        "stations_matched": len(station_ids),
        "station_ids": station_ids,
        "source_labels": sorted(source_labels),
    }
    return {
        "observations": observations,
        "measurements": measurements,
        "stations": stations,
        "lineage": lineage,
        "errors": errors,
        "source": "emodnet_physics",
        "catalog_count": len(stations),
        "catalog_stations": stations,
        "cache_paths": [],
        "network_ids": ["ERDDAP"],
    }
