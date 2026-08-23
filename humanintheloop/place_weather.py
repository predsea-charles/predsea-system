from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import route_analysis
from place_registry import (
    PLACE_CATALOG,
    available_place_ids,
    default_place_id_for_query,
    place_definition,
    resolve_place_query,
    place_family,
    place_pair_metrics,
    station_candidates_for_place,
)

try:
    import ingest_atmosphere
except Exception:  # pragma: no cover - import-time fallback
    ingest_atmosphere = None


LOCAL_TIMEZONE = "Europe/Madrid"
MPS_TO_KNOTS = 1.94384


def available_place_ids():
    return sorted(PLACE_CATALOG)


def place_definition(place_id, latitude=None, longitude=None):
    if place_id == "current_position":
        lat = float(latitude) if latitude is not None else 0.0
        lon = float(longitude) if longitude is not None else 0.0
        return {
            "id": "current_position",
            "name": f"Coordinate ({lat}, {lon})",
            "latitude": lat,
            "longitude": lon,
            "kind": "coordinate",
            "observation_candidates": (),
        }
    canonical_place_id = default_place_id_for_query(place_id) or place_id
    try:
        return PLACE_CATALOG[canonical_place_id]
    except KeyError as error:
        available = ", ".join(available_place_ids())
        raise ValueError(f"Unknown place '{place_id}'. Available places: {available}") from error


def place_route(place_id, latitude=None, longitude=None):
    place = place_definition(place_id, latitude=latitude, longitude=longitude)
    point = {
        "name": place["name"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
    }
    return {
        "id": place_id,
        "name": place["name"],
        "origin": point,
        "destination": point,
        "sample_points": place_sample_points(place),
    }


def place_connection_metrics(origin_place_id, destination_place_id):
    return place_pair_metrics(origin_place_id, destination_place_id)


def place_sample_points(place):
    latitude = float(place["latitude"])
    longitude = float(place["longitude"])
    offsets = [
        (0.0, 0.0),
        (0.03, 0.0),
        (-0.03, 0.0),
        (0.0, 0.03),
        (0.0, -0.03),
        (0.06, 0.0),
        (-0.06, 0.0),
        (0.0, 0.06),
        (0.0, -0.06),
    ]
    return [
        {
            "name": place["name"],
            "latitude": round(latitude + lat_offset, 5),
            "longitude": round(longitude + lon_offset, 5),
        }
        for lat_offset, lon_offset in offsets
    ]


def resolve_place(place_id, latitude=None, longitude=None):
    if place_id == "current_position" and latitude is not None and longitude is not None:
        return {
            "requested_place_id": place_id,
            "place_id": "current_position",
            "place_name": f"Coordinate ({latitude}, {longitude})",
            "latitude": latitude,
            "longitude": longitude,
            "requested_latitude": latitude,
            "requested_longitude": longitude,
            "distance_to_place_nm": 0.0,
            "matched": True,
            "confidence": "high",
        }
    
    resolution = resolve_place_query(place_id)
    canonical_place_id = resolution["place_id"] or default_place_id_for_query(place_id) or place_id
    if latitude is None or longitude is None:
        place = place_definition(canonical_place_id)
        return {
            "requested_place_id": place_id,
            "place_id": canonical_place_id,
            "place_name": place["name"],
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "matched": resolution["matched"],
            "confidence": resolution["confidence"],
        }

    nearest_id, distance_nm = nearest_place_id(latitude, longitude)
    place = place_definition(nearest_id)
    return {
        "requested_place_id": place_id,
        "place_id": nearest_id,
        "place_name": place["name"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "requested_latitude": latitude,
        "requested_longitude": longitude,
        "distance_to_place_nm": round(distance_nm, 1),
        "matched": True,
        "confidence": "high",
    }


def nearest_place_id(latitude, longitude):
    nearest = min(
        available_place_ids(),
        key=lambda place_id: route_analysis.haversine_nm(
            latitude,
            longitude,
            PLACE_CATALOG[place_id]["latitude"],
            PLACE_CATALOG[place_id]["longitude"],
        ),
    )
    distance = route_analysis.haversine_nm(
        latitude,
        longitude,
        PLACE_CATALOG[nearest]["latitude"],
        PLACE_CATALOG[nearest]["longitude"],
    )
    return nearest, distance


def build_place_weather_record(
    place_id,
    forecast,
    observation=None,
    generated_at_utc=None,
    run_date=None,
    run_id=None,
    time_text=None,
    timezone_name=LOCAL_TIMEZONE,
    requested_latitude=None,
    requested_longitude=None,
):
    place = place_definition(place_id, latitude=requested_latitude, longitude=requested_longitude)
    hourly = forecast.get("hourly") or []
    sample = select_hourly_sample(hourly, time_text=time_text, run_date=run_date)
    if not sample:
        # Fallback to a placeholder if no data matches
        sample = {}
    generated_at = generated_at_utc or current_timestamp_utc()
    observation = normalize_observation(observation, generated_at_utc=generated_at)
    observation_age_minutes = observation_age(observation, generated_at)
    freshness_status, freshness_state, freshness_warning = freshness_from_age(observation_age_minutes, observation=observation)
    resolved = resolve_place(place_id, requested_latitude, requested_longitude)
    inside_domain = in_supported_domain(resolved["latitude"], resolved["longitude"])
    payload = {
        "place_id": resolved["place_id"],
        "requested_place_id": resolved["requested_place_id"],
        "place_name": resolved["place_name"],
        "place_kind": place.get("kind"),
        "parent_place_id": place.get("parent_place_id"),
        "place_children": list(place.get("children") or ()),
        "requested_latitude": resolved.get("requested_latitude"),
        "requested_longitude": resolved.get("requested_longitude"),
        "resolved_latitude": resolved["latitude"],
        "resolved_longitude": resolved["longitude"],
        "distance_to_place_nm": resolved.get("distance_to_place_nm"),
        "inside_domain": inside_domain,
        "domain_warning": None if inside_domain else "Requested place is outside the supported forecast domain; using the nearest supported sample.",
        "date": run_date,
        "run": run_id,
        "generated_at_utc": generated_at,
        "timezone": timezone_name,
        "time_utc": sample.get("time_utc"),
        "time_local": to_local_time(sample.get("time_utc"), timezone_name) or sample.get("time"),
        "wave_height_m": sample.get("wave_m"),
        "wave_direction_deg": sample.get("wave_direction_deg"),
        "wave_sea_state": sample.get("wave_sea_state"),
        "swell_1_height_m": sample.get("swell_1_height_m"),
        "swell_1_direction_deg": sample.get("swell_1_direction_deg"),
        "swell_2_height_m": sample.get("swell_2_height_m"),
        "swell_2_direction_deg": sample.get("swell_2_direction_deg"),
        "wind_wave_height_m": sample.get("wind_wave_height_m"),
        "wind_wave_direction_deg": sample.get("wind_wave_direction_deg"),
        "current_kn": sample.get("current_kn"),
        "current_direction_deg": sample.get("current_direction_deg"),
        "wind_kn": observation.get("wind_kn") or sample.get("wind_speed_kn"),
        "wind_gust_kn": observation.get("wind_gust_kn") or sample.get("wind_gust_kn"),
        "wind_direction_deg": observation.get("wind_direction_deg") or sample.get("wind_direction_deg"),
        "water_temperature_c": observation.get("water_temperature_c") or observation.get("water_temp_c") or sample.get("water_temperature_c"),
        "air_temperature_c": observation.get("air_temperature_c") or observation.get("temperature_c") or sample.get("air_temperature_c"),
        "source": "copernicus_med",
        "source_system": "place_weather",
        "freshness_status": freshness_status,
        "freshness_state": freshness_state,
        "freshness_warning": freshness_warning,
        "observation": observation,
        "hourly": hourly,
        "metadata": {
            "observation_age_minutes": observation_age_minutes,
            "catalog_place_name": place["name"],
            "place_kind": place.get("kind"),
            "parent_place_id": place.get("parent_place_id"),
            "place_children": list(place.get("children") or ()),
            "place_family": place_family(place_id),
        },
    }
    if observation.get("last_sample_utc") and parse_utc_timestamp(observation.get("last_sample_utc")) is not None:
        payload["observed_at_utc"] = observation["last_sample_utc"]
        payload["source_time_coordinate_utc"] = observation.get("source_time_coordinate_utc") or observation["last_sample_utc"]
    return payload


def build_place_weather_outputs(
    run_dir,
    run_date,
    run_id,
    waves_path,
    currents_path,
    wind_path=None,
    observations=None,
    station_metadata=None,
    place_ids=None,
    time_text=None,
    timezone_name=LOCAL_TIMEZONE,
):
    """Build and write place weather outputs for all configured places.
    
    Parameters
    ----------
    run_dir : Path or str
        Root output directory for this run
    run_date : str
        Date string (YYYY-MM-DD)
    run_id : str
        Run ID string
    waves_path : str
        Path to waves NetCDF file
    currents_path : str
        Path to currents NetCDF file
    observations : dict, optional
        Observations dict from ingest_observations.fetch_all_observations()
        Should have structure: {station_id: {name, wave_height_m, last_sample_utc, ...}}
    place_ids : list, optional
        List of place IDs to generate. Defaults to all available places.
    time_text : str, optional
        Time string for hourly sample selection
    timezone_name : str
        Timezone name for local time conversion
    
    Returns
    -------
    dict
        Mapping of place_id -> Path to generated weather.json file
    """
    run_dir = Path(run_dir)
    place_ids = list(place_ids or available_place_ids())
    results = {}
    
    # Ensure observations is a dict
    if observations is None:
        observations = {}
    
    for place_id in place_ids:
        record = build_place_weather_bundle_from_files(
            place_id,
            waves_path,
            currents_path,
            wind_path=wind_path,
            observations=observations,
            run_date=run_date,
            run_id=run_id,
            time_text=time_text,
            timezone_name=timezone_name,
        )
        place_dir = run_dir / "places" / place_id
        place_dir.mkdir(parents=True, exist_ok=True)
        (place_dir / "weather.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        results[place_id] = place_dir / "weather.json"

    (run_dir / "places").mkdir(parents=True, exist_ok=True)
    (run_dir / "places" / "index.json").write_text(
        json.dumps(
            {
                "run_date": run_date,
                "run_id": run_id,
                "places": place_ids,
                "created_at_utc": current_timestamp_utc(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return results


def write_place_weather_outputs(
    run_dir,
    run_date,
    run_id,
    waves_path,
    currents_path,
    wind_path=None,
    observations=None,
    station_metadata=None,
    place_ids=None,
    time_text=None,
    timezone_name=LOCAL_TIMEZONE,
):
    """Wrapper for build_place_weather_outputs with proper observation handling."""
    return build_place_weather_outputs(
        run_dir,
        run_date,
        run_id,
        waves_path,
        currents_path,
        wind_path=wind_path,
        observations=observations,
        station_metadata=station_metadata,
        place_ids=place_ids,
        time_text=time_text,
        timezone_name=timezone_name,
    )


def build_place_weather_bundle_from_files(
    place_id,
    waves_path,
    currents_path,
    wind_path=None,
    observations=None,
    station_metadata=None,
    run_date=None,
    run_id=None,
    time_text=None,
    timezone_name=LOCAL_TIMEZONE,
    latitude=None,
    longitude=None,
):
    """Build a complete place weather record from data files.
    
    Parameters
    ----------
    place_id : str
        Place identifier
    waves_path : str or Path
        Path to waves NetCDF file
    currents_path : str or Path
        Path to currents NetCDF file
    observations : dict, optional
        Observations dict from ingest_observations.fetch_all_observations()
        Structure: {station_id: {name, wave_height_m, last_sample_utc, ...}}
    run_date : str, optional
        Date string for metadata
    run_id : str, optional
        Run ID for metadata
    time_text : str, optional
        Time for hourly sample selection
    timezone_name : str
        Timezone for local time conversion
    latitude : float, optional
        Manual latitude for coordinate sampling
    longitude : float, optional
        Manual longitude for coordinate sampling
    
    Returns
    -------
    dict
        Complete place weather payload with observations included
    """
    route = place_route(place_id, latitude=latitude, longitude=longitude)
    forecast = route_analysis.forecast_summary_from_files(
        waves_path, currents_path, wind_path=wind_path, route=route
    )
    observation = select_observation_for_place(place_id, observations or {}, latitude=latitude, longitude=longitude)
    return build_place_weather_record(
        place_id,
        forecast,
        observation=observation,
        generated_at_utc=current_timestamp_utc(),
        run_date=run_date,
        run_id=run_id,
        time_text=time_text,
        timezone_name=timezone_name,
        requested_latitude=latitude,
        requested_longitude=longitude,
    )


def select_hourly_sample(hourly, time_text=None, run_date=None):
    if not hourly:
        return None
    
    # If we have a run_date, try to find the first hour of that date
    if run_date and not time_text:
        for sample in hourly:
            sample_time_utc = sample.get("time_utc", "")
            if sample_time_utc.startswith(run_date):
                return sample
                
    if not time_text:
        return hourly[0]
    return route_analysis.closest_hourly_sample(hourly, time_text)


def select_observation_for_place(place_id, observations, latitude=None, longitude=None):
    """Select the best observation for a given place.
    
    Tries to match observations by:
    1. Pre-configured observation_keys for the place
    2. Place ID as fallback key
    3. Fuzzy matching on station name/aliases
    
    Parameters
    ----------
    place_id : str
        Place identifier
    observations : dict
        Observations dict: {station_id: {name, wave_height_m, last_sample_utc, ...}}
    
    Returns
    -------
    dict
        Normalized observation record, or empty dict if no match found
    """
    place = place_definition(place_id, latitude=latitude, longitude=longitude)
    observation_keys = list(station_candidates_for_place(place_id, latitude=latitude, longitude=longitude)) + [place_id]
    lowered_aliases = [alias.lower() for alias in place.get("aliases") or ()]

    # First: try exact key matches from observation_keys
    for key in observation_keys:
        record = observations.get(key)
        if isinstance(record, dict):
            return normalize_observation(record, station_id=key)

    # Second: fuzzy match on station name/aliases
    for station_id, record in observations.items():
        if not isinstance(record, dict):
            continue
        haystack = " ".join(
            str(value).lower()
            for value in (
                station_id,
                record.get("name"),
                record.get("station_name"),
            )
            if value
        )
        if place_id.lower() in haystack or place["name"].lower() in haystack or any(alias in haystack for alias in lowered_aliases):
            return normalize_observation(record, station_id=station_id)

    # No match found
    return {}


def normalize_observation(record, station_id=None, generated_at_utc=None):
    """Normalize observation record for consistent field names.
    
    Parameters
    ----------
    record : dict
        Raw observation record
    station_id : str, optional
        Station/buoy identifier
    
    Returns
    -------
    dict
        Normalized observation with consistent field names
    """
    if not isinstance(record, dict):
        return {}
    normalized = dict(record)
    if station_id and "station_id" not in normalized:
        normalized["station_id"] = station_id
    if "station_name" not in normalized and normalized.get("name"):
        normalized["station_name"] = normalized.get("name")
    if normalized.get("wind_kn") is None:
        wind_speed = normalized.get("wind_speed_kn")
        if wind_speed is None:
            wind_speed = normalized.get("wind_speed")
        if wind_speed is None:
            wind_speed = normalized.get("wind_speed_mps")
            if wind_speed is not None:
                try:
                    wind_speed = float(wind_speed) * MPS_TO_KNOTS
                except (TypeError, ValueError):
                    wind_speed = None
        if wind_speed is not None:
            normalized["wind_kn"] = wind_speed
    if normalized.get("wind_gust_kn") is None:
        wind_gust = normalized.get("wind_gust_kn_val")
        if wind_gust is None:
            wind_gust = normalized.get("wind_gust")
        if wind_gust is None:
            wind_gust = normalized.get("wind_speed_gust")
        if wind_gust is None:
            wind_gust = normalized.get("gust_kn")
        if wind_gust is None:
            wind_gust = normalized.get("gust")
        if wind_gust is None:
            wind_gust = normalized.get("wind_gust_mps")
            if wind_gust is not None:
                try:
                    wind_gust = float(wind_gust) * MPS_TO_KNOTS
                except (TypeError, ValueError):
                    wind_gust = None
        else:
            if "wind_speed_mps" in normalized or "wind_gust_mps" in normalized:
                try:
                    wind_gust = float(wind_gust) * MPS_TO_KNOTS
                except (TypeError, ValueError):
                    wind_gust = None
            else:
                try:
                    wind_gust = float(wind_gust)
                except (TypeError, ValueError):
                    wind_gust = None
        if wind_gust is not None:
            normalized["wind_gust_kn"] = wind_gust
    if "wind_direction_deg" in normalized:
        val = normalized.get("wind_direction_deg")
        if val is not None:
            if isinstance(val, (int, float)):
                normalized["wind_direction_deg"] = float(val)
            elif isinstance(val, str):
                val_str = val.strip().upper()
                try:
                    normalized["wind_direction_deg"] = float(val_str)
                except ValueError:
                    cardinal_map = {
                        "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5,
                        "E": 90.0, "ESE": 112.5, "SE": 135.0, "SSE": 157.5,
                        "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
                        "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5
                    }
                    normalized["wind_direction_deg"] = cardinal_map.get(val_str)
    if generated_at_utc is not None:
        generated_at = parse_utc_timestamp(generated_at_utc)
        observed_at = parse_utc_timestamp(normalized.get("last_sample_utc") or normalized.get("observed_at_utc"))
        if generated_at is not None and observed_at is not None and observed_at > generated_at + timedelta(minutes=5):
            normalized["is_future"] = True
            normalized["freshness_state"] = "FUTURE"
        elif "is_future" not in normalized:
            normalized["is_future"] = False
    return normalized



def observation_age(observation, generated_at_utc):
    """Calculate observation age in minutes.
    
    Parameters
    ----------
    observation : dict
        Observation record with last_sample_utc or observed_at_utc
    generated_at_utc : str
        Timestamp when record was generated (ISO format)
    
    Returns
    -------
    int or None
        Age in minutes, or None if timestamps unavailable
    """
    observed_at = parse_utc_timestamp(observation.get("last_sample_utc") or observation.get("observed_at_utc"))
    generated_at = parse_utc_timestamp(generated_at_utc)
    if observed_at is None or generated_at is None:
        return None
    if observed_at > generated_at + timedelta(minutes=5):
        return None
    delta = generated_at - observed_at
    return int(round(delta.total_seconds() / 60.0))


def freshness_from_age(age_minutes, observation=None):
    """Determine freshness status/state based on observation age.
    
    Parameters
    ----------
    age_minutes : int or None
        Age of observation in minutes
    
    Returns
    -------
    tuple
        (freshness_status, freshness_state, freshness_warning)
    """
    if observation and observation.get("is_future"):
        return "unknown", "FUTURE", "Observation timestamp is in the future; do not treat this as live."
    if age_minutes is None:
        return "unknown", "UNKNOWN", None
    if age_minutes < 120:
        return "fresh", "LIVE", None
    if age_minutes < 360:
        return "usable", "RECENT", "Observation is getting older; recheck before committing."
    if age_minutes < 720:
        return "stale", "AGING", "Observation is aging; recheck before committing."
    return "stale", "STALE", "Observation is stale; recheck before departure."


def in_supported_domain(latitude, longitude):
    if ingest_atmosphere is None:
        return True
    bbox = getattr(ingest_atmosphere, "WESTMED_BBOX", None)
    if bbox is None:
        bbox = {"south": 35.0, "north": 44.5, "west": -6.5, "east": 16.5}
    return bbox["south"] <= latitude <= bbox["north"] and bbox["west"] <= longitude <= bbox["east"]


def parse_utc_timestamp(value):
    if not value:
        return None
    text = str(value).replace(" UTC", "Z")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(str(value))
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                return None


def to_local_time(value, timezone_name=LOCAL_TIMEZONE):
    timestamp = parse_utc_timestamp(value)
    if timestamp is None:
        return None
    try:
        local_timezone = ZoneInfo(timezone_name)
    except Exception:
        local_timezone = ZoneInfo("Europe/Madrid")
    return timestamp.astimezone(local_timezone).strftime("%Y-%m-%d %H:%M LT")


def current_timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
