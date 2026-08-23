"""Portus observation ingestion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import portus_client
import portus_config
import portus_parsers
import portus_stations


def _format_portus_datetime(value):
    return value.strftime("%Y%m%d@%H%M")


def _default_window(now=None):
    now = now or datetime.now(timezone.utc)
    return now - timedelta(hours=portus_config.DEFAULT_LOOKBACK_HOURS), now


def _unpack_payload(result):
    if isinstance(result, tuple) and len(result) == 2:
        return result
    return result, None


def _normalized_latest_portus_observation(latest):
    normalized = dict(latest or {})
    if "hs_m" in normalized and normalized.get("hs_m") is not None:
        normalized.setdefault("wave_height_m", normalized.get("hs_m"))
    if "wave_direction_deg" in normalized and normalized.get("wave_direction_deg") is not None:
        normalized.setdefault("wave_from_direction_deg", normalized.get("wave_direction_deg"))
    if "wind_speed_mps" in normalized and normalized.get("wind_speed_mps") is not None:
        normalized.setdefault("wind_speed_mps", normalized.get("wind_speed_mps"))
    if "wind_direction_deg" in normalized and normalized.get("wind_direction_deg") is not None:
        normalized.setdefault("wind_direction_deg", normalized.get("wind_direction_deg"))
    if "wind_gust_mps" in normalized and normalized.get("wind_gust_mps") is not None:
        normalized.setdefault("wind_gust_mps", normalized.get("wind_gust_mps"))
    if "current_speed_mps" in normalized and normalized.get("current_speed_mps") is not None:
        normalized.setdefault("current_speed_mps", normalized.get("current_speed_mps"))
    if "current_direction_deg" in normalized and normalized.get("current_direction_deg") is not None:
        normalized.setdefault("current_direction_deg", normalized.get("current_direction_deg"))
    if "temperature_c" in normalized and normalized.get("temperature_c") is not None:
        normalized.setdefault("temperature_c", normalized.get("temperature_c"))
    if "water_temperature_c" in normalized and normalized.get("water_temperature_c") is not None:
        normalized.setdefault("water_temperature_c", normalized.get("water_temperature_c"))
    return normalized


def fetch_station_observation_series(
    station_code,
    *,
    params=None,
    from_dt=None,
    to_dt=None,
    timeout=portus_config.DEFAULT_TIMEOUT_SECONDS,
    max_retries=portus_config.DEFAULT_MAX_RETRIES,
    backoff_seconds=portus_config.DEFAULT_BACKOFF_SECONDS,
    cache_dir=portus_config.RAW_CACHE_DIR,
    session=None,
    dry_run=False,
):
    if dry_run:
        return {
            "available": True,
            "source": "puertos_portus",
            "station_code": str(station_code),
            "dry_run": True,
            "params": list(params) if params else None,
        }

    default_from, default_to = _default_window()
    from_dt = from_dt or default_from
    to_dt = to_dt or default_to
    query_params = {
        "code": str(station_code),
        "from": _format_portus_datetime(from_dt),
        "to": _format_portus_datetime(to_dt),
    }
    if params:
        query_params["params"] = ",".join(params)

    cache_key = f"station_{station_code}_{query_params['from']}_{query_params['to']}"
    payload_result = portus_client.fetch_json(
        portus_config.OBSERVATION_ENDPOINT,
        params=query_params,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=cache_key,
        session=session,
    )
    payload, raw_cache_path = _unpack_payload(payload_result)

    frame = portus_parsers.parse_station_data(payload, station_code)
    print(
        "Portus observations fetched: "
        f"endpoint={portus_config.OBSERVATION_ENDPOINT} "
        f"station_code={station_code} "
        f"from={query_params['from']} "
        f"to={query_params['to']} "
        f"rows={len(frame)}",
        flush=True,
    )
    return {
        "available": True,
        "source": "puertos_portus",
        "station_code": str(station_code),
        "params": list(params) if params else None,
        "from_utc": from_dt.isoformat(),
        "to_utc": to_dt.isoformat(),
        "row_count": len(frame),
        "raw_cache_path": str(raw_cache_path) if raw_cache_path else None,
        "normalized_cache_path": str(
            portus_client.cache_payload(
                cache_dir,
                f"{cache_key}_normalized",
                frame.to_dict(orient="records"),
            )
        ) if cache_dir is not None else None,
        "dataframe": frame,
        "records": frame.to_dict(orient="records"),
    }


def fetch_portus_observations(
    *,
    station_definitions=None,
    params=None,
    timeout=portus_config.DEFAULT_TIMEOUT_SECONDS,
    max_retries=portus_config.DEFAULT_MAX_RETRIES,
    backoff_seconds=portus_config.DEFAULT_BACKOFF_SECONDS,
    cache_dir=portus_config.RAW_CACHE_DIR,
    session=None,
    dry_run=False,
    now=None,
):
    station_definitions = station_definitions or portus_stations.load_observation_stations()
    if not station_definitions:
        return {
            "observations": {},
            "series": {},
            "lineage": {
                "source": None,
                "status": "unavailable",
                "stations_matched": 0,
                "station_ids": [],
            },
            "errors": {"portus": "no station definitions configured"},
        }

    observations = {}
    series = {}
    errors = {}
    cache_paths = []
    matched_station_codes = []

    for station in station_definitions:
        station_code = station["code"]
        try:
            result = fetch_station_observation_series(
                station_code,
                params=params,
                timeout=timeout,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
                cache_dir=cache_dir,
                session=session,
                dry_run=dry_run,
            )
            if result.get("dry_run"):
                observations[station["key"]] = {
                    "source": "puertos_portus",
                    "station_code": str(station_code),
                    "station_name": station["label"],
                    "dry_run": True,
                }
                continue

            frame = result["dataframe"]
            if frame.empty:
                errors[station["key"]] = "no rows returned"
                continue

            series[station["key"]] = result["records"]
            latest = frame.sort_values("time_utc").iloc[-1].to_dict()
            latest = {
                key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in latest.items()
            }
            latest = _normalized_latest_portus_observation(latest)
            observations[station["key"]] = {
                "source": "puertos_portus",
                "station_code": str(station_code),
                "station_name": station["label"],
                "last_sample_utc": latest.get("time_utc"),
                "row_count": result["row_count"],
                "latest": latest,
                "raw_cache_path": result.get("raw_cache_path"),
            }
            cache_paths.append(result.get("raw_cache_path"))
            matched_station_codes.append(str(station_code))
        except Exception as error:
            errors[station["key"]] = str(error)

    status = "matched_successfully" if observations else "unavailable"
    source = "puertos_portus" if observations else None
    return {
        "observations": observations,
        "series": series,
        "lineage": {
            "source": source,
            "status": status,
            "stations_matched": len(matched_station_codes),
            "station_ids": matched_station_codes,
            "cache_paths": [path for path in cache_paths if path],
        },
        "errors": errors,
    }
