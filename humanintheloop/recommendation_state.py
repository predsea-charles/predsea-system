from __future__ import annotations

import copy


_CACHE = {}


def cache_key(snapshot, vessel_class=None):
    forecast = snapshot.get("forecast") or {}
    return (
        snapshot.get("route_id"),
        snapshot.get("run_id"),
        snapshot.get("created_at_utc"),
        vessel_class or snapshot.get("vessel_class"),
        forecast.get("wave_peak_time"),
        forecast.get("wave_max_m"),
        forecast.get("target_local_date"),
        forecast.get("target_period_label"),
        repr(snapshot.get("data_lineage") or {}),
        repr(snapshot.get("request_context") or {}),
    )


def snapshot_signature(snapshot):
    forecast = snapshot.get("forecast") or {}
    alignment = snapshot.get("observation_alignment") or {}
    sanity = snapshot.get("forecast_sanity") or {}
    freshness = snapshot.get("evidence_freshness") or {}
    return (
        forecast.get("wave_min_m"),
        forecast.get("wave_max_m"),
        forecast.get("wave_peak_time"),
        forecast.get("wave_peak_direction_deg"),
        forecast.get("wave_peak_sea_state"),
        forecast.get("current_max_kn"),
        forecast.get("current_peak_time"),
        forecast.get("current_peak_direction_deg"),
        forecast.get("swell_1_height_m"),
        forecast.get("swell_1_direction_deg"),
        forecast.get("swell_2_height_m"),
        forecast.get("swell_2_direction_deg"),
        forecast.get("wind_wave_height_m"),
        forecast.get("wind_wave_direction_deg"),
        alignment.get("agreement"),
        alignment.get("freshness"),
        freshness.get("freshness_status"),
        tuple(sorted((sanity.get("flags") or {}).keys())),
    )


def get_or_build_stance(snapshot, build_fn, vessel_class=None):
    key = cache_key(snapshot, vessel_class=vessel_class)
    signature = snapshot_signature(snapshot)
    cached = _CACHE.get(key)
    if cached and cached.get("signature") == signature:
        return copy.deepcopy(cached["stance"])

    stance = build_fn()
    _CACHE[key] = {"signature": signature, "stance": copy.deepcopy(stance)}
    return stance


def clear_cache():
    _CACHE.clear()
