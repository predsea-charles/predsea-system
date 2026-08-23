from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .common import (
    NETWORK_LABELS,
    parse_utc_timestamp,
    select_spatial_point,
    timestamp_text,
    to_float,
)


FRESHNESS_LABELS = {
    "live": "LIVE",
    "recent": "RECENT",
    "aging": "AGING",
    "stale": "STALE",
    "future": "FUTURE",
    "unknown": "UNKNOWN",
}

FRESHNESS_SCORE = {
    "live": 1.0,
    "recent": 0.85,
    "aging": 0.65,
    "stale": 0.35,
    "future": 0.0,
    "unknown": 0.25,
}

SOURCE_RELIABILITY = {
    "socib": 1.0,
    "redext": 0.95,
    "redcos": 0.9,
    "hfradar": 0.85,
    "puertos_portus": 0.8,
    "redmar": 0.55,
    "puertos_del_estado": 0.8,
}


def _time_dim_name(da):
    for dim in da.dims:
        if dim.lower() in {"time", "time_counter", "datetime"}:
            return dim
    return None


def _series_from_dataarray(da, *, time_dim):
    candidate = da.transpose(time_dim, ...)
    values = np.asarray(candidate.values)
    if values.ndim == 0:
        values = values.reshape(1)
    elif values.ndim > 1:
        values = values.reshape(values.shape[0], -1)[:, 0]
    times = pd.to_datetime(np.asarray(candidate[time_dim].values), utc=True, errors="coerce")
    if len(values) != len(times):
        limit = min(len(values), len(times))
        values = values[:limit]
        times = times[:limit]
    return times, values


def _fill_values_from_dataarray(da, extra_fill_values=None):
    values = set()
    for key in ("_FillValue", "missing_value", "fill_value"):
        if key in da.attrs and da.attrs[key] is not None:
            raw = da.attrs[key]
            if isinstance(raw, (list, tuple, set)):
                values.update(raw)
            else:
                values.add(raw)
    if extra_fill_values:
        if isinstance(extra_fill_values, (list, tuple, set)):
            values.update(extra_fill_values)
        else:
            values.add(extra_fill_values)
    return values


def _is_fill_value(value, fill_values):
    if value is None or pd.isna(value):
        return True
    for candidate in fill_values or ():
        if candidate is None or pd.isna(candidate):
            continue
        try:
            if float(value) == float(candidate):
                return True
        except Exception:
            if value == candidate:
                return True
    return False


def freshness_status_from_sample_time(sample_time_utc, *, now_utc=None, tolerance_minutes=5):
    sample_dt = parse_utc_timestamp(sample_time_utc)
    reference_dt = parse_utc_timestamp(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    if sample_dt is None or reference_dt is None:
        return "unknown"
    delta_minutes = (reference_dt - sample_dt).total_seconds() / 60.0
    if delta_minutes < -tolerance_minutes:
        return "future"
    if delta_minutes < 120:
        return "live"
    if delta_minutes < 360:
        return "recent"
    if delta_minutes < 720:
        return "aging"
    return "stale"


def freshness_state_from_sample_time(sample_time_utc, *, now_utc=None, tolerance_minutes=5):
    return FRESHNESS_LABELS.get(
        freshness_status_from_sample_time(sample_time_utc, now_utc=now_utc, tolerance_minutes=tolerance_minutes),
        "UNKNOWN",
    )


def source_reliability_for(record=None, *, network=None, source_system=None, source_label=None):
    network = str(network or (record or {}).get("network") or "").lower()
    source_system = str(source_system or (record or {}).get("source_system") or (record or {}).get("provider") or "").lower()
    source_label = str(source_label or (record or {}).get("source_label") or "").lower()
    if network in SOURCE_RELIABILITY:
        return SOURCE_RELIABILITY[network]
    if source_system in SOURCE_RELIABILITY:
        return SOURCE_RELIABILITY[source_system]
    if "socib" in source_system or "socib" in source_label:
        return SOURCE_RELIABILITY["socib"]
    if "radar" in source_label:
        return SOURCE_RELIABILITY["hfradar"]
    return 0.75


def qc_value_is_good(qc_flag):
    if qc_flag is None:
        return None
    try:
        return int(qc_flag) in (1, 2)
    except Exception:
        return None


def quality_score_for_sample(
    *,
    freshness_status=None,
    qc_flag=None,
    is_qc_good=None,
    network=None,
    source_system=None,
    source_label=None,
    distance_to_route_nm=None,
):
    freshness_status = (freshness_status or "unknown").lower()
    freshness_component = FRESHNESS_SCORE.get(freshness_status, FRESHNESS_SCORE["unknown"])
    if is_qc_good is None:
        is_qc_good = qc_value_is_good(qc_flag)
    if is_qc_good is None:
        qc_component = 0.75
    else:
        qc_component = 1.0 if is_qc_good else 0.45
    reliability_component = source_reliability_for(
        network=network,
        source_system=source_system,
        source_label=source_label,
    )
    if distance_to_route_nm is None:
        route_component = 0.75
    else:
        try:
            route_distance = float(distance_to_route_nm)
        except Exception:
            route_distance = None
        if route_distance is None:
            route_component = 0.75
        else:
            route_component = max(0.1, 1.0 - min(route_distance, 120.0) / 120.0)
    score = (
        freshness_component * 0.4
        + qc_component * 0.3
        + reliability_component * 0.2
        + route_component * 0.1
    )
    return round(max(0.0, min(1.0, score)), 2)


def latest_valid_sample_from_dataarray(
    da,
    *,
    qc_da=None,
    fill_values=None,
    now_utc=None,
    tolerance_minutes=5,
    latitude=None,
    longitude=None,
):
    candidate = da
    if latitude is not None and longitude is not None:
        candidate = select_spatial_point(candidate, latitude, longitude)
    time_dim = _time_dim_name(candidate)
    if time_dim is None:
        return None
    for dim in list(candidate.dims):
        if dim != time_dim and candidate.sizes.get(dim, 0) == 1:
            candidate = candidate.isel({dim: 0}, drop=True)
    try:
        candidate = candidate.transpose(time_dim, ...)
    except Exception:
        pass
    times, values = _series_from_dataarray(candidate, time_dim=time_dim)
    if len(times) == 0:
        return None
    qc_values = None
    if qc_da is not None:
        qc_candidate = qc_da
        if latitude is not None and longitude is not None:
            qc_candidate = select_spatial_point(qc_candidate, latitude, longitude)
        qc_time_dim = _time_dim_name(qc_candidate)
        if qc_time_dim is not None:
            for dim in list(qc_candidate.dims):
                if dim != qc_time_dim and qc_candidate.sizes.get(dim, 0) == 1:
                    qc_candidate = qc_candidate.isel({dim: 0}, drop=True)
            try:
                qc_candidate = qc_candidate.transpose(qc_time_dim, ...)
            except Exception:
                pass
            qc_times, qc_values = _series_from_dataarray(qc_candidate, time_dim=qc_time_dim)
            if len(qc_times) != len(times):
                # fall back to positional alignment if coordinates drift
                qc_values = np.asarray(qc_candidate.values).reshape(-1)[: len(times)]
                if len(qc_values) < len(times):
                    qc_values = None
    now_dt = parse_utc_timestamp(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    fill_values = _fill_values_from_dataarray(candidate, fill_values)
    valid_indexes = []
    for index, (time_value, value) in enumerate(zip(times, values)):
        if pd.isna(time_value) or _is_fill_value(value, fill_values):
            continue
        valid_indexes.append(index)
    if not valid_indexes:
        return None
    latest_index = valid_indexes[-1]
    sample_time = timestamp_text(times[latest_index])
    freshness_status = freshness_status_from_sample_time(sample_time, now_utc=now_dt, tolerance_minutes=tolerance_minutes)
    qc_flag = None
    if qc_values is not None and latest_index < len(qc_values):
        qc_flag = qc_values[latest_index]
        try:
            qc_flag = int(qc_flag) if qc_flag is not None else None
        except Exception:
            qc_flag = None
    is_qc_good = qc_value_is_good(qc_flag)
    return {
        "selected_index": latest_index,
        "value": to_float(values[latest_index]),
        "source_time_coordinate_utc": sample_time,
        "sample_time_utc": sample_time,
        "observed_at_utc": sample_time,
        "is_future_timestamp": freshness_status == "future",
        "is_future": freshness_status == "future",
        "freshness_status": freshness_status,
        "freshness_state": FRESHNESS_LABELS.get(freshness_status, "UNKNOWN"),
        "qc_flag": qc_flag,
        "is_qc_good": is_qc_good,
        "quality_score": quality_score_for_sample(
            freshness_status=freshness_status,
            qc_flag=qc_flag,
            is_qc_good=is_qc_good,
            network=getattr(candidate, "attrs", {}).get("network"),
            source_system=getattr(candidate, "attrs", {}).get("source_system"),
            source_label=getattr(candidate, "attrs", {}).get("source_label"),
        ),
    }


def sampled_valid_samples_from_dataarray(
    da,
    *,
    qc_da=None,
    fill_values=None,
    now_utc=None,
    latitude=None,
    longitude=None,
    tolerance_minutes=5,
    sample_frequency="1h",
):
    candidate = da
    if latitude is not None and longitude is not None:
        candidate = select_spatial_point(candidate, latitude, longitude)
    time_dim = _time_dim_name(candidate)
    if time_dim is None:
        return []
    for dim in list(candidate.dims):
        if dim != time_dim and candidate.sizes.get(dim, 0) == 1:
            candidate = candidate.isel({dim: 0}, drop=True)
    try:
        candidate = candidate.transpose(time_dim, ...)
    except Exception:
        pass
    times, values = _series_from_dataarray(candidate, time_dim=time_dim)
    if len(times) == 0:
        return []

    time_index = pd.DatetimeIndex(times)
    fill_values = _fill_values_from_dataarray(candidate, fill_values)
    valid_indexes = []
    for index, (time_value, value) in enumerate(zip(time_index, values)):
        if pd.isna(time_value) or _is_fill_value(value, fill_values):
            continue
        valid_indexes.append(index)
    if not valid_indexes:
        return []

    qc_values = None
    if qc_da is not None:
        qc_candidate = qc_da
        if latitude is not None and longitude is not None:
            qc_candidate = select_spatial_point(qc_candidate, latitude, longitude)
        qc_time_dim = _time_dim_name(qc_candidate)
        if qc_time_dim is not None:
            for dim in list(qc_candidate.dims):
                if dim != qc_time_dim and qc_candidate.sizes.get(dim, 0) == 1:
                    qc_candidate = qc_candidate.isel({dim: 0}, drop=True)
            try:
                qc_candidate = qc_candidate.transpose(qc_time_dim, ...)
            except Exception:
                pass
            qc_times, qc_values = _series_from_dataarray(qc_candidate, time_dim=qc_time_dim)
            if len(qc_times) != len(time_index):
                qc_values = np.asarray(qc_candidate.values).reshape(-1)[: len(time_index)]
                if len(qc_values) < len(time_index):
                    qc_values = None

    valid_times = time_index[valid_indexes]
    start = valid_times.min().floor(sample_frequency)
    end = valid_times.max().floor(sample_frequency)
    if end < start:
        end = start
    sampled_times = pd.date_range(start=start, end=end, freq=sample_frequency)
    now_dt = parse_utc_timestamp(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    samples = []

    for target_time in sampled_times:
        try:
            nearest_index = int(time_index.get_indexer([target_time], method="nearest")[0])
        except Exception:
            continue
        if nearest_index < 0 or nearest_index >= len(time_index):
            continue
        source_time = time_index[nearest_index]
        value = values[nearest_index]
        if pd.isna(source_time) or _is_fill_value(value, fill_values):
            continue
        qc_flag = None
        if qc_values is not None and nearest_index < len(qc_values):
            qc_flag = qc_values[nearest_index]
            try:
                qc_flag = int(qc_flag) if qc_flag is not None else None
            except Exception:
                qc_flag = None
        freshness_status = freshness_status_from_sample_time(target_time, now_utc=now_dt, tolerance_minutes=tolerance_minutes)
        is_qc_good = qc_value_is_good(qc_flag)
        samples.append(
            {
                "selected_index": nearest_index,
                "value": to_float(value),
                "source_time_coordinate_utc": timestamp_text(source_time),
                "sample_time_utc": timestamp_text(target_time),
                "observed_at_utc": timestamp_text(target_time),
                "is_future_timestamp": freshness_status == "future",
                "is_future": freshness_status == "future",
                "freshness_status": freshness_status,
                "freshness_state": FRESHNESS_LABELS.get(freshness_status, "UNKNOWN"),
                "qc_flag": qc_flag,
                "is_qc_good": is_qc_good,
                "quality_score": quality_score_for_sample(
                    freshness_status=freshness_status,
                    qc_flag=qc_flag,
                    is_qc_good=is_qc_good,
                    network=getattr(candidate, "attrs", {}).get("network"),
                    source_system=getattr(candidate, "attrs", {}).get("source_system"),
                    source_label=getattr(candidate, "attrs", {}).get("source_label"),
                ),
            }
        )

    return samples


def qc_flag_for_sample(
    ds,
    source_field,
    sample_time_utc,
    *,
    latitude=None,
    longitude=None,
):
    qc_candidates = (
        f"{source_field}_QC",
        f"{source_field}_qc",
        f"{source_field}_DM",
        f"{source_field}_dm",
    )
    sample_dt = parse_utc_timestamp(sample_time_utc)
    if sample_dt is None:
        return None
    for candidate_name in qc_candidates:
        if candidate_name not in ds.data_vars:
            continue
        da = ds[candidate_name]
        if latitude is not None and longitude is not None:
            da = select_spatial_point(da, latitude, longitude)
        time_dim = _time_dim_name(da)
        if time_dim is None:
            continue
        for dim in list(da.dims):
            if dim != time_dim and da.sizes.get(dim, 0) == 1:
                da = da.isel({dim: 0}, drop=True)
        try:
            da = da.transpose(time_dim, ...)
        except Exception:
            pass
        times, values = _series_from_dataarray(da, time_dim=time_dim)
        if len(times) == 0:
            continue
        candidate_indexes = [
            index
            for index, time_value in enumerate(times)
            if pd.notna(time_value) and time_value.to_pydatetime() <= sample_dt
        ]
        if not candidate_indexes:
            continue
        latest_index = candidate_indexes[-1]
        qc_value = values[latest_index]
        if qc_value is None:
            continue
        try:
            return int(qc_value)
        except Exception:
            continue
    return None


def build_measurement_record(
    station_meta,
    *,
    raw_key,
    variable,
    source_field,
    value,
    units=None,
    sample=None,
    qc_flag=None,
    is_qc_good=None,
    source_label=None,
    source_system=None,
    dataset_url=None,
    latitude=None,
    longitude=None,
    station_kind=None,
    distance_to_route_nm=None,
    nearest_routes=None,
):
    sample = sample or {}
    source_system = source_system or station_meta.get("source_system") or "puertos_del_estado"
    network = station_meta.get("network") or sample.get("network")
    source_label = source_label or station_meta.get("source_label") or NETWORK_LABELS.get(network, source_system.upper())
    freshness_status = sample.get("freshness_status") or freshness_status_from_sample_time(sample.get("sample_time_utc"))
    if is_qc_good is None:
        is_qc_good = sample.get("is_qc_good")
    if qc_flag is None:
        qc_flag = sample.get("qc_flag")
    if distance_to_route_nm is None:
        distance_to_route_nm = station_meta.get("distance_to_route_nm")
    quality_score = quality_score_for_sample(
        freshness_status=freshness_status,
        qc_flag=qc_flag,
        is_qc_good=is_qc_good,
        network=network,
        source_system=source_system,
        source_label=source_label,
        distance_to_route_nm=distance_to_route_nm,
    )
    sample_time_utc = sample.get("sample_time_utc")
    source_time_coordinate_utc = sample.get("source_time_coordinate_utc") or sample_time_utc
    record = {
        "source": source_system,
        "source_system": source_system,
        "source_label": source_label,
        "provider": source_system,
        "network": network,
        "station_id": station_meta.get("station_id"),
        "station_name": station_meta.get("station_name"),
        "catalog_id": station_meta.get("catalog_id"),
        "catalog_url": station_meta.get("catalog_url"),
        "dataset_url": dataset_url,
        "latitude": latitude if latitude is not None else station_meta.get("latitude"),
        "longitude": longitude if longitude is not None else station_meta.get("longitude"),
        "station_kind": station_kind if station_kind is not None else station_meta.get("station_kind"),
        "source_field": source_field,
        "variable": variable,
        "raw_key": raw_key,
        "value": value,
        "units": units,
        "qc_flag": qc_flag,
        "is_qc_good": is_qc_good,
        "is_future_timestamp": freshness_status == "future",
        "is_future": freshness_status == "future",
        "freshness_status": freshness_status,
        "freshness_state": FRESHNESS_LABELS.get(freshness_status, "UNKNOWN"),
        "quality_score": quality_score,
        "source_time_coordinate_utc": source_time_coordinate_utc,
        "sample_time_utc": sample_time_utc,
        "observed_at_utc": sample.get("observed_at_utc") or sample_time_utc,
        "nearest_routes": list(nearest_routes or station_meta.get("nearest_routes") or []),
        "distance_to_route_nm": distance_to_route_nm,
    }
    return record
