from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import place_weather
import route_analysis
from place_registry import default_place_id_for_query
import source_lineage


CONFIDENCE_ORDER = {"Low": 0, "Medium": 1, "High": 2}


def compute_route_reliability(store, route_id, run_date, run_id, snapshot):
    route = _safe_load_route(route_id)
    origin_place_id, destination_place_id = _route_place_ids(route)
    current_records, offline_sources = _current_place_weather_records(
        store,
        run_date=run_date,
        run_id=run_id,
        place_ids=[origin_place_id, destination_place_id],
    )
    snapshot_timestamp = _timestamp_from_snapshot(snapshot)
    evidence_timestamp = _oldest_timestamp([snapshot_timestamp, *_record_timestamps(current_records)])
    age_minutes = _age_minutes(evidence_timestamp)
    source_summary = source_lineage.summarize_sources(snapshot=snapshot, observations=None)
    source_breadth_score = source_lineage.source_breadth_score(source_summary)

    method = _evaluation_method(snapshot, current_records)
    if method == "multi_model_consensus":
        variance_pct = _multi_model_variance(snapshot, current_records)
        comparison = "multi_model_consensus"
        comparison_detail = _multi_model_detail(snapshot, current_records, variance_pct)
    else:
        variance_pct = _single_model_variance(store, route_id, run_date, run_id, snapshot)
        comparison = "current_vs_previous_route_snapshot"
        comparison_detail = _single_model_detail(
            store,
            route_id,
            run_date,
            run_id,
            snapshot,
            variance_pct,
        )

    freshness_score = _score_from_age(age_minutes)
    variance_score = _score_from_variance(variance_pct, method)
    if method == "single_model_consistency" and variance_pct is None:
        variance_score = "Medium" if source_breadth_score in {"Medium", "High"} else "Low"
    confidence_score = _lower_score(freshness_score, variance_score)
    confidence_score = _lower_score(confidence_score, source_breadth_score)
    confidence_score = _apply_offline_penalty(confidence_score, offline_sources)
    reason = _reliability_reason(
        age_minutes,
        freshness_score,
        variance_pct,
        variance_score,
        comparison_detail,
        offline_sources,
        source_summary,
    )

    return {
        "confidence_score": confidence_score,
        "evaluation_method": method,
        "age_minutes": age_minutes,
        "reason": reason,
        "details": {
            "comparison": comparison,
            "freshness_score": freshness_score,
            "variance_score": variance_score,
            "source_breadth_score": source_breadth_score,
            "variance_pct": variance_pct,
            "freshness_age_minutes": age_minutes,
            "offline_sources": offline_sources,
            "offline_source_count": len(offline_sources),
            "source_summary": source_summary,
            **comparison_detail,
        },
    }


def _safe_load_route(route_id):
    try:
        return route_analysis.load_route(route_id)
    except Exception:
        return {}


def _route_place_ids(route):
    origin = route.get("origin") or {}
    destination = route.get("destination") or {}
    origin_place_id = route.get("origin_place_id") or origin.get("place_id") or origin.get("id")
    destination_place_id = route.get("destination_place_id") or destination.get("place_id") or destination.get("id")
    if not origin_place_id and origin.get("name"):
        origin_place_id = default_place_id_for_query(origin.get("name"))
    if not destination_place_id and destination.get("name"):
        destination_place_id = default_place_id_for_query(destination.get("name"))
    return origin_place_id, destination_place_id


def _current_place_weather_records(store, run_date, run_id, place_ids):
    records = []
    offline_sources = []
    for place_id in place_ids:
        if not place_id:
            continue
        try:
            payload = store.load_place_weather(place_id, run_date, run_id)
        except Exception:
            offline_sources.append(place_id)
            continue
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["place_id"] = payload.get("place_id") or place_id
            records.append(payload)
        else:
            offline_sources.append(place_id)
    return records, sorted(set(offline_sources))


def _timestamp_from_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return None
    candidates = [
        snapshot.get("created_at_utc"),
        (snapshot.get("forecast") or {}).get("created_at_utc"),
        (snapshot.get("forecast") or {}).get("source_snapshot_created_at_utc"),
    ]
    for candidate in candidates:
        timestamp = place_weather.parse_utc_timestamp(candidate)
        if timestamp is not None:
            return timestamp
    return None


def _record_timestamps(records):
    timestamps = []
    for record in records:
        for key in ("source_time_coordinate_utc", "observed_at_utc", "generated_at_utc", "last_sample_utc"):
            timestamp = place_weather.parse_utc_timestamp(record.get(key))
            if timestamp is not None:
                timestamps.append(timestamp)
                break
    return timestamps


def _oldest_timestamp(timestamps):
    valid = [timestamp for timestamp in timestamps if timestamp is not None]
    if not valid:
        return None
    return min(valid)


def _age_minutes(timestamp):
    if timestamp is None:
        return 999
    now = datetime.now(timezone.utc)
    delta = now - timestamp.astimezone(timezone.utc)
    return max(0, int(round(delta.total_seconds() / 60.0)))


def _evaluation_method(snapshot, records):
    forecast_sources = _forecast_sources(snapshot)
    if len(forecast_sources) >= 2 and len(_numeric_values(records)) >= 2:
        return "multi_model_consensus"
    return "single_model_consistency"


def _forecast_sources(snapshot):
    if not isinstance(snapshot, dict):
        return set()
    forecast = snapshot.get("forecast") or {}
    sources = forecast.get("forecast_sources") or snapshot.get("forecast_sources") or []
    normalized = set()
    for source in sources:
        if isinstance(source, dict):
            source_id = source.get("id") or source.get("label") or source.get("name")
        else:
            source_id = source
        if source_id:
            normalized.add(str(source_id).strip().lower())
    return normalized


def _source_identity(record):
    if not isinstance(record, dict):
        return None
    for key in ("source_label", "network", "source_system"):
        value = record.get(key)
        if value:
            return str(value).strip().lower()
    return None


def _numeric_values(records):
    values = []
    for record in records:
        value = _primary_metric(record)
        if value is not None:
            values.append((record, value))
    return values


def _primary_metric(record):
    if not isinstance(record, dict):
        return None
    for key in ("wave_height_m", "wave_m", "current_kn", "wind_kn"):
        value = record.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    observation = record.get("observation") if isinstance(record.get("observation"), dict) else None
    if observation:
        for key in ("wave_height_m", "wave_m", "current_kn", "wind_kn"):
            value = observation.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _route_forecast_metric(snapshot):
    if not isinstance(snapshot, dict):
        return None
    forecast = snapshot.get("forecast") or {}
    if isinstance(forecast.get("wave_max_m"), (int, float)):
        return float(forecast["wave_max_m"])
    passage = forecast.get("passage_evidence") or {}
    worst = passage.get("worst_segment") or {}
    for key in ("wave_m", "current_kn"):
        value = worst.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    for key in ("current_max_kn", "wave_min_m"):
        value = forecast.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _multi_model_variance(snapshot, records):
    forecast_metric = _route_forecast_metric(snapshot)
    if forecast_metric is None:
        values = _numeric_values(records)
        if len(values) < 2:
            return None
        forecast_metric = values[0][1]
        baseline_metric = values[1][1]
    else:
        values = _numeric_values(records)
        if not values:
            return None
        baseline_metric = sum(value for _, value in values) / float(len(values))
    return _variance_pct(forecast_metric, baseline_metric)


def _single_model_variance(store, route_id, run_date, run_id, snapshot):
    current_metric = _snapshot_consistency_metric(snapshot)
    if current_metric is None:
        return None
    previous_ref = _previous_route_snapshot_ref(store, route_id, run_date, run_id)
    if previous_ref is None:
        return None
    try:
        previous_snapshot = store.load_snapshot(
            route_id,
            previous_ref["run_date"],
            previous_ref["run_id"],
        )
    except Exception:
        return None
    previous_metric = _snapshot_consistency_metric(previous_snapshot)
    if previous_metric is None:
        return None
    return _variance_pct(current_metric, previous_metric)


def _single_model_detail(store, route_id, run_date, run_id, snapshot, variance_pct):
    previous_ref = _previous_route_snapshot_ref(store, route_id, run_date, run_id)
    current_metric = _snapshot_consistency_metric(snapshot)
    previous_metric = None
    if previous_ref is not None:
        try:
            previous_snapshot = store.load_snapshot(
                route_id,
                previous_ref["run_date"],
                previous_ref["run_id"],
            )
            previous_metric = _snapshot_consistency_metric(previous_snapshot)
        except Exception:
            previous_snapshot = None
    return {
        "current_run_id": run_id,
        "previous_run_id": previous_ref["run_id"] if previous_ref else None,
        "previous_run_date": previous_ref["run_date"] if previous_ref else None,
        "current_metric": current_metric,
        "previous_metric": previous_metric,
        "comparison_kind": "snapshot_scalar",
        "threshold_pct": 10 if _score_from_variance(variance_pct, "single_model_consistency") == "High" else 25,
    }


def _multi_model_detail(snapshot, records, variance_pct):
    values = _numeric_values(records)
    current_metric = _route_forecast_metric(snapshot)
    baseline_metric = None
    if len(values) >= 2:
        baseline_metric = sum(value for _, value in values) / float(len(values))
    return {
        "current_metric": current_metric,
        "baseline_metric": baseline_metric,
        "comparison_kind": "forecast_sources",
        "source_count": len(_forecast_sources(snapshot)),
        "threshold_pct": 15 if _score_from_variance(variance_pct, "multi_model_consensus") == "High" else 30,
    }


def _reliability_reason(
    age_minutes,
    freshness_score,
    variance_pct,
    variance_score,
    comparison_detail,
    offline_sources=None,
    source_summary=None,
):
    reasons = []
    offline_sources = offline_sources or []
    source_summary = source_lineage.normalize_source_summary(source_summary or {})
    if freshness_score == "Low":
        if age_minutes is None or age_minutes >= 999:
            reasons.append("Evidence timestamp is unavailable, so confidence stays conservative.")
        else:
            reasons.append(f"Evidence is old at about {age_minutes} minutes.")
    if offline_sources:
        names = ", ".join(offline_sources)
        reasons.append(f"One or more route sources were offline or unavailable: {names}.")
    if variance_score == "Low":
        previous_run_id = comparison_detail.get("previous_run_id")
        previous_run_date = comparison_detail.get("previous_run_date")
        if previous_run_id is None and comparison_detail.get("comparison_kind") == "snapshot_scalar":
            if previous_run_date:
                reasons.append(
                    f"Compared against the previous forecast snapshot from {previous_run_date} {previous_run_id}."
                )
            else:
                if source_summary.get("count", 0) > 1:
                    reasons.append(
                        "Previous route snapshot is missing, so the score leans on current freshness and source breadth."
                    )
                else:
                    reasons.append("Previous route snapshot is missing, so the run-over-run comparison is conservative.")
        elif previous_run_id is not None:
            reasons.append(
                f"Compared against the previous forecast snapshot from {previous_run_date} {previous_run_id}."
            )
        elif variance_pct is None:
            reasons.append("The route comparison signal is too weak to measure reliably.")
        else:
            threshold = comparison_detail.get("threshold_pct")
            reasons.append(
                f"The route comparison changed by about {variance_pct:.1f}% which is above the safe threshold of {threshold}%."
            )
    if source_summary.get("count", 0) > 1:
        reasons.append(f"Multiple active source families are available: {source_summary.get('text').removeprefix('Sources used: ') if source_summary.get('text') else ', '.join(source_summary.get('sources') or [])}.")
    elif source_summary.get("count", 0) == 1:
        reasons.append(f"Only one active source family is available: {', '.join(source_summary.get('sources') or [])}.")
    if not reasons:
        if variance_score == "Medium" or freshness_score == "Medium":
            reasons.append("The route looks usable, but one of the checks is only moderate.")
        else:
            reasons.append("Freshness and run-over-run consistency both look acceptable.")
    return " ".join(reasons)


def _apply_offline_penalty(confidence_score, offline_sources):
    if not offline_sources or confidence_score == "Low":
        return confidence_score
    if confidence_score == "High":
        return "Medium"
    if confidence_score == "Medium":
        return "Low"
    return confidence_score


def _snapshot_consistency_metric(snapshot):
    if not isinstance(snapshot, dict):
        return None
    forecast = snapshot.get("forecast") or {}
    passage = forecast.get("passage_evidence") or {}
    worst = passage.get("worst_segment") or {}
    for key in ("wave_m", "current_kn"):
        value = worst.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    for key in ("wave_max_m", "current_max_kn", "wave_min_m"):
        value = forecast.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    observations = snapshot.get("observations") or {}
    for record in observations.values():
        if isinstance(record, dict):
            value = _primary_metric(record)
            if value is not None:
                return value
    return None


def _previous_route_snapshot_ref(store, route_id, run_date, run_id):
    dates = _sorted_available_dates(store)
    if not dates:
        return None
    if run_date not in dates:
        dates = sorted(dates + [run_date])
    current_index = dates.index(run_date)
    current_run_ids = _run_ids_for_date(store, run_date)
    current_prior = _prior_run_id(current_run_ids, run_id)
    if current_prior is not None:
        return {"run_date": run_date, "run_id": current_prior}
    for previous_date in reversed(dates[:current_index]):
        prior_run_ids = _run_ids_for_date(store, previous_date)
        if prior_run_ids:
            return {"run_date": previous_date, "run_id": prior_run_ids[-1]}
    return None


def _sorted_available_dates(store):
    try:
        dates = list(store.available_dates())
    except Exception:
        return []
    return sorted(date for date in dates if isinstance(date, str))


def _run_ids_for_date(store, run_date):
    runs_dir = _runs_dir_for(store, run_date)
    if runs_dir is None or not runs_dir.exists():
        return []
    return sorted(path.name for path in runs_dir.iterdir() if path.is_dir())


def _prior_run_id(run_ids, run_id):
    if not run_ids:
        return None
    if run_id in run_ids:
        index = run_ids.index(run_id)
        if index > 0:
            return run_ids[index - 1]
        return None
    prior = [candidate for candidate in run_ids if candidate < run_id]
    if prior:
        return prior[-1]
    return None


def _runs_dir_for(store, run_date):
    base = getattr(store, "predictions_root", None)
    if base is not None:
        return Path(base) / run_date / "runs"
    fallback = getattr(store, "fallback_store", None)
    fallback_base = getattr(fallback, "predictions_root", None)
    if fallback_base is not None:
        return Path(fallback_base) / run_date / "runs"
    return None


def _variance_pct(current, baseline):
    if current is None or baseline is None:
        return None
    baseline = float(baseline)
    if baseline == 0.0:
        return None
    return abs(float(current) - baseline) / abs(baseline) * 100.0


def _score_from_age(age_minutes):
    if age_minutes is None:
        return "Low"
    if age_minutes < 180:
        return "High"
    if age_minutes <= 360:
        return "Medium"
    return "Low"


def _score_from_variance(variance_pct, method):
    if variance_pct is None:
        return "Low"
    if method == "multi_model_consensus":
        if variance_pct < 15:
            return "High"
        if variance_pct <= 30:
            return "Medium"
        return "Low"
    if variance_pct < 10:
        return "High"
    if variance_pct <= 25:
        return "Medium"
    return "Low"


def _lower_score(*scores):
    filtered = [score for score in scores if score in CONFIDENCE_ORDER]
    if not filtered:
        return "Low"
    return min(filtered, key=lambda score: CONFIDENCE_ORDER[score])
