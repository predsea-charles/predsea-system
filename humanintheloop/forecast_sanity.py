from __future__ import annotations

from datetime import datetime
import re


def forecast_sanity(snapshot_or_forecast):
    forecast = snapshot_or_forecast.get("forecast") if isinstance(snapshot_or_forecast, dict) and "forecast" in snapshot_or_forecast else snapshot_or_forecast
    forecast = forecast or {}
    hourly = forecast.get("hourly") or []

    warnings = []
    flags = {}

    wave_series = [row.get("wave_m") for row in hourly if isinstance(row, dict)]
    time_series = [row.get("time") for row in hourly if isinstance(row, dict)]
    if len(wave_series) >= 2:
        for index in range(len(wave_series) - 1):
            current = wave_series[index]
            nxt = wave_series[index + 1]
            if current is None or nxt is None:
                continue
            delta = float(nxt) - float(current)
            if abs(delta) > 1.0 and _hours_apart(time_series[index], time_series[index + 1]) <= 2:
                if delta < 0:
                    flags["rapid_wave_drop"] = True
                    warnings.append("rapid_wave_drop")
                else:
                    flags["rapid_wave_increase"] = True
                    warnings.append("rapid_wave_increase")

    direction_series = [row.get("wave_direction_deg") for row in hourly if isinstance(row, dict)]
    for index in range(len(direction_series) - 1):
        current = direction_series[index]
        nxt = direction_series[index + 1]
        if current is None or nxt is None:
            continue
        delta = abs(_signed_angle_delta(current, nxt))
        if delta >= 120 and _hours_apart(time_series[index], time_series[index + 1]) <= 3:
            flags["rapid_swell_direction_shift"] = True
            warnings.append("rapid_swell_direction_shift")
            break

    wave_max = forecast.get("wave_max_m")
    wave_min = forecast.get("wave_min_m")
    if isinstance(wave_max, (int, float)) and isinstance(wave_min, (int, float)):
        if wave_max - wave_min >= 1.0 and len(hourly) >= 2:
            flags["large_wave_range"] = True
            warnings.append("large_wave_range")

    if not warnings:
        warnings.append("no_sanity_flags")

    return {
        "warnings": warnings,
        "flags": flags,
        "summary": _human_summary(warnings),
    }


def _human_summary(warnings):
    if warnings == ["no_sanity_flags"]:
        return "Forecast evolution looks broadly stable."
    labels = {
        "rapid_wave_drop": "Forecast wave height drops unusually fast",
        "rapid_wave_increase": "Forecast wave height rises unusually fast",
        "rapid_swell_direction_shift": "Swell direction shifts unusually quickly",
        "large_wave_range": "Forecast wave range is unusually broad",
    }
    parts = [labels.get(warning, warning.replace("_", " ")) for warning in warnings]
    return "; ".join(dict.fromkeys(parts))


def _hours_apart(time_a, time_b):
    hour_a = _minutes_from_time(time_a)
    hour_b = _minutes_from_time(time_b)
    if hour_a is None or hour_b is None:
        return 24
    return abs(hour_b - hour_a) / 60.0


def _minutes_from_time(value):
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", str(value))
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _signed_angle_delta(left, right):
    try:
        left = float(left)
        right = float(right)
    except (TypeError, ValueError):
        return 0.0
    return ((right - left + 540.0) % 360.0) - 180.0
