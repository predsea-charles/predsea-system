from __future__ import annotations

from .normalize_observations import freshness_status_from_sample_time, freshness_state_from_sample_time, quality_score_for_sample


def measurements_to_observation_record(station_meta, measurements):
    if not measurements:
        return None
    measurements = sorted(
        measurements,
        key=lambda item: (item.get("sample_time_utc") or "", item.get("source_field") or ""),
    )
    latest_sample_time = max(
        (measurement.get("sample_time_utc") for measurement in measurements if measurement.get("sample_time_utc")),
        default=None,
    )
    latest_measurement = max(
        measurements,
        key=lambda measurement: measurement.get("sample_time_utc") or "",
    )
    source_system = station_meta.get("source_system") or "puertos_del_estado"
    source_label = station_meta.get("source_label") or station_meta.get("network_label") or "Puertos del Estado"
    record = {
        "source": source_system,
        "source_system": source_system,
        "source_label": source_label,
        "provider": source_system,
        "network": station_meta.get("network"),
        "station_id": station_meta.get("station_id"),
        "station_name": station_meta.get("station_name"),
        "catalog_id": station_meta.get("catalog_id"),
        "catalog_url": station_meta.get("catalog_url"),
        "last_sample_utc": latest_sample_time,
        "sample_time_utc": latest_sample_time,
        "observed_at_utc": latest_sample_time,
        "source_time_coordinate_utc": latest_measurement.get("source_time_coordinate_utc") or latest_sample_time,
        "latitude": station_meta.get("latitude"),
        "longitude": station_meta.get("longitude"),
        "station_kind": station_meta.get("station_kind"),
        "nearest_routes": list(station_meta.get("nearest_routes") or []),
        "distance_to_route_nm": station_meta.get("distance_to_route_nm"),
        "qc_flag": latest_measurement.get("qc_flag"),
        "is_qc_good": latest_measurement.get("is_qc_good"),
        "is_future": bool(latest_measurement.get("is_future")),
        "is_future_timestamp": bool(latest_measurement.get("is_future_timestamp") or latest_measurement.get("is_future")),
        "freshness_status": latest_measurement.get("freshness_status")
        or freshness_status_from_sample_time(latest_sample_time),
        "freshness_state": latest_measurement.get("freshness_state")
        or freshness_state_from_sample_time(latest_sample_time),
        "quality_score": latest_measurement.get("quality_score")
        or quality_score_for_sample(
            freshness_status=latest_measurement.get("freshness_status")
            or freshness_status_from_sample_time(latest_sample_time),
            qc_flag=latest_measurement.get("qc_flag"),
            is_qc_good=latest_measurement.get("is_qc_good"),
            network=station_meta.get("network"),
            source_system=source_system,
            source_label=source_label,
            distance_to_route_nm=station_meta.get("distance_to_route_nm"),
        ),
        "measurements": measurements,
    }
    for measurement in measurements:
        raw_key = measurement.get("raw_key")
        if not raw_key:
            continue
        record[raw_key] = measurement.get("value")
        record[f"{raw_key}_source_field"] = measurement.get("source_field")
        if measurement.get("units") is not None:
            record[f"{raw_key}_units"] = measurement.get("units")
        if measurement.get("qc_flag") is not None:
            record[f"{raw_key}_qc_flag"] = measurement.get("qc_flag")
        if measurement.get("source_time_coordinate_utc") is not None:
            record[f"{raw_key}_source_time_coordinate_utc"] = measurement.get("source_time_coordinate_utc")
    return record
