import json
from datetime import datetime, timezone
from pathlib import Path

import route_analysis
from place_registry import place_definition as resolve_place_definition


SCHEMA_VERSION = "predsea.validation.v1"

OBSERVATION_VARIABLES = {
    "sea_level_m": ("sea_level", "m"),
    "sea_level_residual_m": ("sea_level_residual", "m"),
    "depth_m": ("depth", "m"),
    "wave_height_m": ("wave_height", "m"),
    "wave_from_direction_deg": ("wave_direction", "degree"),
    "wave_direction_deg": ("wave_direction", "degree"),
    "hs_m": ("wave_height", "m"),
    "hmax_m": ("wave_height_max", "m"),
    "wave_height_max_m": ("wave_height_max", "m"),
    "wave_period_peak_s": ("wave_period_peak", "s"),
    "wave_period_mean_s": ("wave_period_mean", "s"),
    "wave_peak_direction_deg": ("wave_peak_direction", "degree"),
    "swell_1_height_m": ("swell_1_height", "m"),
    "swell_2_height_m": ("swell_2_height", "m"),
    "wind_speed_mps": ("wind_speed", "m/s"),
    "wind_speed_kn": ("wind_speed", "knots"),
    "wind_direction_deg": ("wind_direction", "degree"),
    "wind_gust_mps": ("wind_gust", "m/s"),
    "wind_gust_kn": ("wind_gust", "knots"),
    "gust_mps": ("wind_gust", "m/s"),
    "gust_kn": ("wind_gust", "knots"),
    "gust": ("wind_gust", "m/s"),
    "temperature_c": ("air_temperature", "celsius"),
    "air_temperature_c": ("air_temperature", "celsius"),
    "water_temp_c": ("water_temperature", "celsius"),
    "water_temperature_c": ("water_temperature", "celsius"),
    "water_temp": ("water_temperature", "celsius"),
    "salinity_psu": ("salinity", "psu"),
    "sea_level_pressure_hpa": ("sea_level_pressure", "hPa"),
    "air_pressure_hpa": ("air_pressure", "hPa"),
    "WSPD": ("wind_speed", "m/s"),
    "WDIR": ("wind_direction", "degree"),
    "DRYT": ("air_temperature", "celsius"),
    "PSAL": ("salinity", "psu"),
    "VHM0_SW1": ("swell_1_height", "m"),
    "VMDR_SW1": ("swell_1_direction", "degree"),
    "current_speed_mps": ("current_speed", "m/s"),
    "current_direction_deg": ("current_direction", "degree"),
    "current_u_mps": ("current_u", "m/s"),
    "current_v_mps": ("current_v", "m/s"),
}

COMPASS_DEGREES = {
    "N": 0.0,
    "NNE": 22.5,
    "NE": 45.0,
    "ENE": 67.5,
    "E": 90.0,
    "ESE": 112.5,
    "SE": 135.0,
    "SSE": 157.5,
    "S": 180.0,
    "SSW": 202.5,
    "SW": 225.0,
    "WSW": 247.5,
    "W": 270.0,
    "WNW": 292.5,
    "NW": 315.0,
    "NNW": 337.5,
}

FORECAST_VARIABLES = {
    "wave_m": ("wave_height", "m"),
    "wave_direction_deg": ("wave_direction", "degree"),
    "current_mps": ("current_speed", "m/s"),
    "current_direction_deg": ("current_direction", "degree"),
    "swell_1_height_m": ("swell_1_height", "m"),
    "swell_1_direction_deg": ("swell_1_direction", "degree"),
    "swell_2_height_m": ("swell_2_height", "m"),
    "swell_2_direction_deg": ("swell_2_direction", "degree"),
    "wind_wave_height_m": ("wind_wave_height", "m"),
    "wind_wave_direction_deg": ("wind_wave_direction", "degree"),
    "wind_speed_kn": ("wind_speed", "knots"),
    "wind_direction_deg": ("wind_direction", "degree"),
    "wind_gust_kn": ("wind_gust", "knots"),
}


def write_validation_archive(
    run_dir,
    run_date,
    run_id,
    routes,
    snapshots_by_route,
    observations,
    output_root,
    station_metadata=None,
    source_inventory=None,
):
    validation_dir = Path(run_dir) / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    observation_rows = build_observation_rows(observations, run_date, run_id)
    forecast_rows = build_forecast_rows(snapshots_by_route, routes, run_date, run_id)
    station_metadata_rows = build_station_metadata_rows(
        observations,
        run_date=run_date,
        run_id=run_id,
        station_metadata=station_metadata,
    )
    source_inventory_rows = build_source_inventory_rows(source_inventory, run_date, run_id)
    historical_forecast_rows = load_historical_forecast_rows(output_root)
    matched_rows = match_observations_to_forecasts(
        observation_rows,
        historical_forecast_rows + forecast_rows,
    )
    summary = build_validation_summary(
        run_date,
        run_id,
        observation_rows,
        forecast_rows,
        matched_rows,
        station_metadata_rows=station_metadata_rows,
        source_inventory_rows=source_inventory_rows,
    )

    write_jsonl(validation_dir / "observation_samples.jsonl", observation_rows)
    write_jsonl(validation_dir / "forecast_index.jsonl", forecast_rows)
    write_jsonl(validation_dir / "matched_validation.jsonl", matched_rows)
    write_jsonl(validation_dir / "station_metadata.jsonl", station_metadata_rows)
    write_jsonl(validation_dir / "source_inventory.jsonl", source_inventory_rows)
    (validation_dir / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_observation_rows(observations, run_date, run_id):
    rows = []
    collected_at_utc = current_timestamp_utc()
    for station_id, record in sorted((observations or {}).items()):
        if not isinstance(record, dict):
            continue
        measurements = record.get("measurements")
        if isinstance(measurements, list) and measurements:
            for measurement in measurements:
                if not isinstance(measurement, dict):
                    continue
                observed_at = normalize_timestamp(
                    measurement.get("observed_at_utc")
                    or measurement.get("sample_time_utc")
                    or measurement.get("source_time_coordinate_utc")
                )
                sample_time = normalize_timestamp(
                    measurement.get("sample_time_utc")
                    or measurement.get("observed_at_utc")
                    or measurement.get("source_time_coordinate_utc")
                )
                source_time_coordinate_utc = normalize_timestamp(
                    measurement.get("source_time_coordinate_utc") or sample_time or observed_at
                )
                freshness_status = (measurement.get("freshness_status") or measurement.get("freshness_state") or "UNKNOWN").lower()
                freshness_state = (measurement.get("freshness_state") or freshness_status or "UNKNOWN").upper()
                qc_flag = measurement.get("qc_flag")
                future_flag = (
                    is_future_timestamp(sample_time, collected_at_utc)
                    or is_future_timestamp(observed_at, collected_at_utc)
                    or is_future_timestamp(source_time_coordinate_utc, collected_at_utc)
                    or measurement.get("is_future")
                    or measurement.get("is_future_timestamp")
                )
                rows.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "record_type": "observation",
                        "source_family": source_family_for_record(measurement, record, default="observation"),
                        "run_date": run_date,
                        "run_id": run_id,
                        "provider": measurement.get("provider") or record.get("provider") or record.get("source") or "socib",
                        "source_system": measurement.get("source_system") or record.get("source_system") or record.get("provider") or record.get("source") or "socib",
                        "source_label": measurement.get("source_label") or record.get("source_label") or record.get("station_name"),
                        "station_id": measurement.get("station_id") or station_id,
                        "station_name": measurement.get("station_name") or record.get("station_name") or record.get("name"),
                        "sample_time_utc": sample_time,
                        "observed_at_utc": observed_at,
                        "source_time_coordinate_utc": source_time_coordinate_utc,
                        "collected_at_utc": collected_at_utc,
                        "variable": measurement.get("variable"),
                        "source_field": measurement.get("source_field") or measurement.get("raw_key"),
                        "value": normalize_observed_value(measurement.get("raw_key") or measurement.get("source_field") or measurement.get("variable"), measurement.get("value")),
                        "raw_value": measurement.get("value"),
                        "units": measurement.get("units"),
                        "qc_flag": qc_flag,
                        "freshness_status": freshness_status if freshness_status != "unknown" else freshness_state_from_observation(observed_at, collected_at_utc).lower(),
                        "freshness_state": freshness_state or freshness_state_from_observation(observed_at, collected_at_utc),
                        "quality_score": numeric_value(measurement.get("quality_score")),
                        "latitude": measurement.get("latitude") if measurement.get("latitude") is not None else record.get("latitude"),
                        "longitude": measurement.get("longitude") if measurement.get("longitude") is not None else record.get("longitude"),
                        "depth_m": measurement.get("depth_m") if measurement.get("depth_m") is not None else record.get("depth_m"),
                        "is_future": bool(future_flag),
                        "is_future_timestamp": bool(future_flag),
                        "is_qc_good": measurement.get("is_qc_good"),
                        "nearest_routes": measurement.get("nearest_routes") or record.get("nearest_routes") or [],
                        "distance_to_route_nm": numeric_value(
                            measurement.get("distance_to_route_nm") if measurement.get("distance_to_route_nm") is not None else record.get("distance_to_route_nm")
                        ),
                        "dataset_url": measurement.get("dataset_url") or record.get("dataset_url"),
                    }
                )
            continue
        sample_time = normalize_timestamp(
            record.get("sample_time_utc") or record.get("last_sample_utc") or record.get("observed_at_utc")
        )
        observed_at = normalize_timestamp(
            record.get("observed_at_utc") or record.get("sample_time_utc") or record.get("last_sample_utc")
        )
        source_time_coordinate_utc = normalize_timestamp(
            record.get("source_time_coordinate_utc") or sample_time or observed_at
        )
        freshness_status = (record.get("freshness_status") or record.get("freshness_state") or "UNKNOWN").lower()
        freshness_state = (record.get("freshness_state") or freshness_status or "UNKNOWN").upper()
        quality_score = numeric_value(record.get("quality_score"))
        future_flag = (
            is_future_timestamp(sample_time, collected_at_utc)
            or is_future_timestamp(observed_at, collected_at_utc)
            or is_future_timestamp(source_time_coordinate_utc, collected_at_utc)
            or record.get("is_future")
            or record.get("is_future_timestamp")
        )
        for raw_key, (variable, units) in OBSERVATION_VARIABLES.items():
            if raw_key not in record or record.get(raw_key) is None:
                continue
            value = normalize_observed_value(raw_key, record.get(raw_key))
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "observation",
                    "source_family": source_family_for_record(record, record, default="observation"),
                    "run_date": run_date,
                    "run_id": run_id,
                    "provider": record.get("provider") or record.get("source") or "socib",
                    "source_system": record.get("source_system") or record.get("provider") or record.get("source") or "socib",
                    "source_label": record.get("source_label") or record.get("station_name"),
                    "station_id": station_id,
                    "station_name": record.get("station_name") or record.get("name"),
                    "sample_time_utc": sample_time,
                    "observed_at_utc": observed_at,
                    "source_time_coordinate_utc": source_time_coordinate_utc,
                    "collected_at_utc": collected_at_utc,
                    "variable": variable,
                    "source_field": raw_key,
                    "value": value,
                    "raw_value": record.get(raw_key),
                    "units": units,
                    "qc_flag": record.get("qc_flag") or record.get(f"{raw_key}_qc_flag"),
                    "freshness_status": freshness_status if freshness_status != "unknown" else freshness_state_from_observation(observed_at, collected_at_utc).lower(),
                    "freshness_state": freshness_state or freshness_state_from_observation(observed_at, collected_at_utc),
                    "quality_score": quality_score,
                    "latitude": record.get("latitude"),
                    "longitude": record.get("longitude"),
                    "depth_m": record.get("depth_m"),
                    "is_future": bool(future_flag),
                    "is_future_timestamp": bool(future_flag),
                    "is_qc_good": record.get("is_qc_good"),
                    "nearest_routes": record.get("nearest_routes") or [],
                    "distance_to_route_nm": numeric_value(record.get("distance_to_route_nm")),
                    "dataset_url": record.get("dataset_url") or record.get("catalog_url"),
                }
            )
    return rows


def build_station_metadata_rows(observations, run_date=None, run_id=None, station_metadata=None):
    rows_by_station = {}
    for station_id, record in sorted((observations or {}).items()):
        if not isinstance(record, dict):
            continue
        row = station_metadata_row_from_record(station_id, record, run_date=run_date, run_id=run_id)
        if row:
            rows_by_station[station_id] = row

    for candidate in normalize_station_metadata_candidates(station_metadata):
        station_id = candidate.get("station_id")
        if not station_id:
            continue
        existing = rows_by_station.get(station_id, {})
        merged = {**existing, **candidate}
        merged.setdefault("source_family", source_family_for_record(candidate, existing, default="observation"))
        merged.setdefault("provider", candidate.get("provider") or existing.get("provider"))
        merged.setdefault("network", candidate.get("network") or existing.get("network"))
        merged.setdefault("station_name", candidate.get("station_name") or existing.get("station_name"))
        merged.setdefault("latitude", candidate.get("latitude") or existing.get("latitude"))
        merged.setdefault("longitude", candidate.get("longitude") or existing.get("longitude"))
        merged.setdefault("station_kind", candidate.get("station_kind") or existing.get("station_kind"))
        merged.setdefault("priority", candidate.get("priority") or existing.get("priority") or "normal")
        merged.setdefault("variables_supported", candidate.get("variables_supported") or existing.get("variables_supported") or [])
        merged.setdefault("nearest_routes", candidate.get("nearest_routes") or existing.get("nearest_routes") or [])
        merged.setdefault("distance_to_route_nm", candidate.get("distance_to_route_nm") or existing.get("distance_to_route_nm"))
        if run_date is not None:
            merged["run_date"] = run_date
        if run_id is not None:
            merged["run_id"] = run_id
        rows_by_station[station_id] = merged

    return sorted(
        rows_by_station.values(),
        key=lambda row: (
            row.get("provider") or "",
            row.get("network") or "",
            row.get("station_name") or "",
            row.get("station_id") or "",
        ),
    )


def build_source_inventory_rows(source_inventory, run_date=None, run_id=None):
    rows = []
    for entry in source_inventory or []:
        if not isinstance(entry, dict):
            continue
        source_status = entry.get("status") or ("active" if entry.get("available") else "unavailable")
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "record_type": "source_inventory",
                "source_family": entry.get("source_family") or source_family_for_record(entry, default="unknown"),
                "run_date": run_date,
                "run_id": run_id,
                "provider": entry.get("provider") or entry.get("id") or entry.get("source_system"),
                "source_system": entry.get("id") or entry.get("source_system") or entry.get("provider"),
                "source_label": entry.get("label") or entry.get("source_label"),
                "station_id": entry.get("station_id") or entry.get("id"),
                "station_name": entry.get("station_name") or entry.get("label") or entry.get("id"),
                "sample_time_utc": normalize_timestamp(entry.get("observed_at_utc") or entry.get("generated_at_utc")),
                "observed_at_utc": normalize_timestamp(entry.get("observed_at_utc") or entry.get("generated_at_utc")),
                "source_time_coordinate_utc": normalize_timestamp(entry.get("observed_at_utc") or entry.get("generated_at_utc")),
                "variable": "source_status",
                "source_field": "available",
                "value": 1.0 if entry.get("available") else 0.0,
                "units": "bool",
                "qc_flag": None,
                "freshness_status": source_status,
                "freshness_state": str(source_status).upper(),
                "quality_score": None,
                "is_future": False,
                "is_future_timestamp": False,
                "is_qc_good": entry.get("available"),
                "dataset_url": entry.get("dataset_url"),
                "source_family": entry.get("source_family") or source_family_for_record(entry, default="unknown"),
                "nearest_routes": [],
                "distance_to_route_nm": None,
                "provider_kind": entry.get("kind"),
                "resolution_km": entry.get("resolution_km"),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row.get("source_system") or "",
            row.get("source_label") or "",
            row.get("station_id") or "",
        ),
    )


def normalize_station_metadata_candidates(station_metadata):
    if not station_metadata:
        return []
    if isinstance(station_metadata, dict):
        candidates = []
        for key, value in station_metadata.items():
            if isinstance(value, dict):
                candidate = dict(value)
                candidate.setdefault("station_id", key)
                candidates.append(candidate)
        return candidates
    return [dict(item) for item in station_metadata if isinstance(item, dict)]


def station_metadata_row_from_record(station_id, record, run_date=None, run_id=None):
    latitude = numeric_value(record.get("latitude"))
    longitude = numeric_value(record.get("longitude"))
    variables_supported = supported_variables_from_record(record)
    if latitude is None and longitude is None and not variables_supported:
        return None
    distance_to_palma = distance_to_place_nm(latitude, longitude, "palma")
    distance_to_ibiza = distance_to_place_nm(latitude, longitude, "ibiza")
    distance_to_menorca = distance_to_place_nm(latitude, longitude, "menorca")
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "station_metadata",
        "source_family": source_family_for_record(record, record, default="observation"),
        "run_date": run_date,
        "run_id": run_id,
        "provider": record.get("provider") or record.get("source") or "socib",
        "network": record.get("network") or infer_network_from_record(record),
        "station_id": station_id,
        "station_name": record.get("station_name") or record.get("name"),
        "station_kind": record.get("station_kind") or infer_station_kind(record),
        "priority": station_priority(record, distance_to_palma, distance_to_ibiza, distance_to_menorca),
        "latitude": latitude,
        "longitude": longitude,
        "depth_m": numeric_value(record.get("depth_m")),
        "variables_supported": variables_supported,
        "nearest_routes": list(record.get("nearest_routes") or []),
        "distance_to_route_nm": numeric_value(record.get("distance_to_route_nm")),
        "distance_to_palma": distance_to_palma,
        "distance_to_ibiza": distance_to_ibiza,
        "distance_to_menorca": distance_to_menorca,
        "source_label": record.get("source_label"),
        "catalog_id": record.get("catalog_id"),
        "catalog_url": record.get("catalog_url"),
        "last_sample_utc": normalize_timestamp(
            record.get("sample_time_utc") or record.get("observed_at_utc") or record.get("last_sample_utc")
        ),
    }


def supported_variables_from_record(record):
    variables = []
    for raw_key, (variable, _units) in OBSERVATION_VARIABLES.items():
        if record.get(raw_key) is not None:
            variables.append(variable)
    if not variables:
        for key, value in record.items():
            if key.endswith(("_m", "_deg", "_kn", "_mps", "_c", "_psu")) and value is not None:
                variables.append(key.rsplit("_", 1)[0])
    return sorted(set(variables))


def infer_network_from_record(record):
    source_label = str(record.get("source_label") or "").upper()
    network = str(record.get("network") or "").lower()
    if network:
        return network
    if source_label in {"REDEXT", "REDCOS", "REDMAR", "HF_RADAR", "EMODNET_PHYSICS"}:
        return source_label.lower()
    source_system = str(record.get("source_system") or record.get("provider") or "").lower()
    if "emodnet" in source_system:
        return "emodnet_physics"
    if "socib" in source_system:
        return "socib"
    return None


def infer_station_kind(record):
    network = infer_network_from_record(record)
    if network == "redmar":
        return "tide_gauge"
    if network in {"redext", "redcos"}:
        return "buoy"
    if network == "hfradar":
        return "radar"
    if network == "emodnet_physics":
        return "platform"
    if network == "socib":
        return "platform"
    return record.get("station_kind")


def station_priority(record, distance_to_palma, distance_to_ibiza, distance_to_menorca):
    explicit_priority = str(record.get("priority") or "").lower()
    if explicit_priority in {"high", "medium", "normal", "low"}:
        return explicit_priority
    station_id = str(record.get("station_id") or "").lower()
    high_priority_ids = {
        "bahia_de_palma",
        "canal_de_ibiza",
        "ibiza",
        "mallorca",
        "puertos_mallorca",
        "puertos_ibiza",
        "puertos_alcudia",
        "puertos_mahon",
        "puertos_formentera",
        "porto_colom",
        "puertos_delta_del_ebro",
    }
    if infer_network_from_record(record) == "hfradar":
        return "high"
    if infer_network_from_record(record) == "redmar":
        return "low"
    if station_id in high_priority_ids:
        return "high"
    distances = [value for value in (distance_to_palma, distance_to_ibiza, distance_to_menorca) if value is not None]
    if not distances:
        return "normal"
    shortest = min(distances)
    if shortest <= 40:
        return "high"
    if shortest <= 90:
        return "medium"
    return "normal"


def distance_to_place_nm(latitude, longitude, place_id):
    if latitude is None or longitude is None:
        return None
    try:
        place = resolve_place_definition(place_id)
    except Exception:
        return None
    return round(
        route_analysis.haversine_nm(latitude, longitude, place["latitude"], place["longitude"]),
        1,
    )


def build_forecast_rows(snapshots_by_route, routes, run_date, run_id):
    rows = []
    for route_id, snapshot in sorted((snapshots_by_route or {}).items()):
        route = routes.get(route_id, {})
        forecast = snapshot.get("forecast", {})
        forecast_source = snapshot.get("forecast_source", {})
        data_lineage = snapshot.get("data_lineage", {})
        validation = route.get("validation", {}) or {}
        current_validation = route.get("current_validation", {}) or {}
        for target in forecast.get("hourly") or []:
            target_time = normalize_timestamp(target.get("time_utc"))
            if not target_time:
                continue
            for source_field, (variable, units) in FORECAST_VARIABLES.items():
                if target.get(source_field) is None:
                    continue
                truth_station = truth_station_for_variable(variable, validation, current_validation)
                rows.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "record_type": "forecast",
                        "source_family": source_family_for_forecast(snapshot, forecast_source),
                        "run_date": run_date,
                        "run_id": run_id,
                        "route_id": route_id,
                        "route_name": route.get("name") or snapshot.get("route"),
                        "forecast_created_at_utc": normalize_timestamp(snapshot.get("created_at_utc")),
                        "forecast_source_id": forecast_source.get("id"),
                        "forecast_source_label": forecast_source.get("label"),
                        "ocean_source": (data_lineage.get("ocean_forecast") or {}).get("source"),
                        "resolution_km": (data_lineage.get("ocean_forecast") or {}).get("resolution_km"),
                        "target_time_utc": target_time,
                        "target_local_time": target.get("time"),
                        "variable": variable,
                        "source_field": source_field,
                        "value": target.get(source_field),
                        "units": units,
                        "truth_station_id": truth_station,
                        "lead_time_hours": lead_time_hours(snapshot.get("created_at_utc"), target_time),
                    }
                )
    return rows


def truth_station_for_variable(variable, wave_validation, current_validation):
    if variable.startswith("current_"):
        return current_validation.get("truth_source")
    if variable.startswith("wave_") or variable.startswith("swell_") or variable.startswith("wind_wave_"):
        return wave_validation.get("truth_source")
    return None


def match_observations_to_forecasts(observation_rows, forecast_rows):
    observations_by_key = {}
    for row in observation_rows:
        key = (row.get("station_id"), row.get("variable"), row.get("observed_at_utc"))
        observations_by_key.setdefault(key, []).append(row)

    matches = []
    seen = set()
    for forecast in forecast_rows:
        if forecast.get("lead_time_hours") is not None and forecast["lead_time_hours"] < 0:
            continue
        station_id = forecast.get("truth_station_id")
        if not station_id:
            continue
        key = (station_id, forecast.get("variable"), forecast.get("target_time_utc"))
        for observation in observations_by_key.get(key, []):
            match_id = "|".join(
                str(part)
                for part in (
                    forecast.get("run_id"),
                    forecast.get("route_id"),
                    forecast.get("target_time_utc"),
                    forecast.get("variable"),
                    station_id,
                )
            )
            if match_id in seen:
                continue
            seen.add(match_id)
            forecast_value = numeric_value(forecast.get("value"))
            observed_value = numeric_value(observation.get("value"))
            matches.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "matched_validation",
                    "match_id": match_id,
                    "route_id": forecast.get("route_id"),
                    "route_name": forecast.get("route_name"),
                    "truth_station_id": station_id,
                    "truth_station_name": observation.get("station_name"),
                    "forecast_run_id": forecast.get("run_id"),
                    "forecast_created_at_utc": forecast.get("forecast_created_at_utc"),
                    "target_time_utc": forecast.get("target_time_utc"),
                    "observed_at_utc": observation.get("observed_at_utc"),
                    "variable": forecast.get("variable"),
                    "forecast_value": forecast.get("value"),
                    "observed_value": observation.get("value"),
                    "units": forecast.get("units"),
                    "error": error_delta(forecast_value, observed_value),
                    "absolute_error": absolute_error(forecast_value, observed_value),
                    "lead_time_hours": forecast.get("lead_time_hours"),
                    "forecast_source_id": forecast.get("forecast_source_id"),
                    "ocean_source": forecast.get("ocean_source"),
                    "resolution_km": forecast.get("resolution_km"),
                }
            )
    return sorted(matches, key=lambda row: (row.get("target_time_utc") or "", row.get("route_id") or "", row.get("variable") or ""))


def build_validation_summary(run_date, run_id, observation_rows, forecast_rows, matched_rows, station_metadata_rows=None, source_inventory_rows=None):
    variable_counts = {}
    for row in matched_rows:
        variable_counts[row["variable"]] = variable_counts.get(row["variable"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "run_id": run_id,
        "created_at_utc": current_timestamp_utc(),
        "observation_rows": len(observation_rows),
        "forecast_rows": len(forecast_rows),
        "matched_rows": len(matched_rows),
        "station_metadata_rows": len(station_metadata_rows or []),
        "source_inventory_rows": len(source_inventory_rows or []),
        "matched_variables": variable_counts,
        "metrics": metrics_by_variable(matched_rows),
        "notes": [
            "Observation archive contains the latest provider samples fetched by this ETL run.",
            "Matched validation links current observations to any saved forecast index with the same station, variable, and target time.",
            "Forecast rows with negative lead time are archived but excluded from matched validation.",
            "Rows accumulate across GitHub/GCS runs when prior forecast_index.jsonl files are available in the output tree.",
        ],
    }


def metrics_by_variable(matched_rows):
    metrics = {}
    for variable in sorted({row.get("variable") for row in matched_rows if row.get("variable")}):
        rows = [row for row in matched_rows if row.get("variable") == variable and row.get("absolute_error") is not None]
        if not rows:
            metrics[variable] = {"count": 0, "mae": None, "bias": None}
            continue
        errors = [row["error"] for row in rows if row.get("error") is not None]
        absolute_errors = [row["absolute_error"] for row in rows]
        metrics[variable] = {
            "count": len(rows),
            "mae": round(sum(absolute_errors) / len(absolute_errors), 3),
            "bias": round(sum(errors) / len(errors), 3) if errors else None,
        }
    return metrics


def load_historical_forecast_rows(output_root):
    root = Path(output_root)
    rows = []
    for path in sorted(root.glob("*/runs/*/validation/forecast_index.jsonl")):
        rows.extend(read_jsonl(path))
    return rows


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, sort_keys=True) + "\n")


def read_jsonl(path):
    rows = []
    try:
        with Path(path).open(encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        return []
    return rows


def normalize_timestamp(value):
    if not value:
        return None
    text = str(value).strip()
    
    # Try parsing as a Unix epoch float (BigQuery TIMESTAMP REST representation)
    try:
        val_float = float(text)
        if 0.0 <= val_float <= 4102444800.0:  # range 1970 to 2100
            return datetime.fromtimestamp(val_float, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        pass
        
    if text.endswith(" UTC"):
        text = text[:-4] + "Z"
    if text.endswith("Z") and "T" not in text:
        text = text[:-1].replace(" ", "T") + "Z"
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ", "%Y-%m-%d %H:%M UTC"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return text


def source_family_for_record(primary, fallback=None, default="unknown"):
    record = primary if isinstance(primary, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    source_system = str(
        record.get("source_system")
        or record.get("provider")
        or fallback.get("source_system")
        or fallback.get("provider")
        or ""
    ).lower()
    source_label = str(
        record.get("source_label")
        or fallback.get("source_label")
        or ""
    ).upper()
    network = str(
        record.get("network")
        or fallback.get("network")
        or ""
    ).lower()
    if "emodnet" in source_system or source_label == "EMODNET_PHYSICS":
        return "observation"
    if "portus" in source_system:
        return "observation"
    if source_label in {"REDMAR", "REDCOS", "REDEXT", "HF_RADAR"}:
        return "observation"
    if network in {"redmar", "redcos", "redext", "hfradar"}:
        return "observation"
    if "atmospheric" in source_system or "wind" in source_system and "forecast" in source_system:
        return "atmosphere"
    if "atmospheric" in source_label.lower() or "wind forecast" in source_label.lower():
        return "atmosphere"
    if "copernicus" in source_system:
        return "ocean_forecast"
    if source_system in {"meteo_france_arome", "aemet_harmonie_arome", "ecmwf_open_data"}:
        return "atmosphere"
    return default


def source_family_for_forecast(snapshot, forecast_source=None):
    source = forecast_source if isinstance(forecast_source, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    source_id = str(
        source.get("id")
        or source.get("source")
        or snapshot.get("forecast_source", {}).get("id")
        or snapshot.get("data_lineage", {}).get("ocean_forecast", {}).get("source")
        or ""
    ).lower()
    if source_id in {"meteo_france_arome", "aemet_harmonie_arome", "ecmwf_open_data"}:
        return "atmosphere"
    if "copernicus" in source_id or source_id == "copernicus_med":
        return "ocean_forecast"
    return "forecast"


def lead_time_hours(created_at, target_time):
    created = parse_timestamp(created_at)
    target = parse_timestamp(target_time)
    if not created or not target:
        return None
    return round((target - created).total_seconds() / 3600, 2)


def parse_timestamp(value):
    normalized = normalize_timestamp(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_future_timestamp(candidate, reference):
    candidate_dt = parse_timestamp(candidate)
    reference_dt = parse_timestamp(reference)
    if candidate_dt is None or reference_dt is None:
        return False
    return candidate_dt > reference_dt


def current_timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def numeric_value(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_observed_value(source_field, value):
    if source_field.endswith("_direction_deg") or source_field == "wave_from_direction_deg":
        if isinstance(value, str):
            compass = value.strip().upper()
            if compass in COMPASS_DEGREES:
                return COMPASS_DEGREES[compass]
    return value


def error_delta(forecast_value, observed_value):
    if forecast_value is None or observed_value is None:
        return None
    return round(forecast_value - observed_value, 3)


def absolute_error(forecast_value, observed_value):
    error = error_delta(forecast_value, observed_value)
    if error is None:
        return None
    return abs(error)


def freshness_state_from_observation(observed_at, collected_at):
    observed = parse_timestamp(observed_at)
    collected = parse_timestamp(collected_at)
    if observed is None or collected is None:
        return "UNKNOWN"
    delta_minutes = (collected - observed).total_seconds() / 60.0
    if delta_minutes < -5:
        return "FUTURE"
    if delta_minutes < 120:
        return "LIVE"
    if delta_minutes < 360:
        return "RECENT"
    if delta_minutes < 720:
        return "AGING"
    return "STALE"
