import argparse
import json
import math
from datetime import date
from datetime import datetime, timezone
from pathlib import Path

import requests
import socib_public
import route_analysis


MVP_DATA_DIR = Path("mvp_data")
VALIDATION_DIR = MVP_DATA_DIR / "validation"
SOCIB_SERIES_URL = "http://apps.socib.es/DataDiscovery/variable-plotting-data"
def load_observations():
    return socib_public.fetch_public_observations()


def validate_route_snapshot(snapshot, observations):
    route_id = snapshot.get("route_id")
    validation_source = route_validation_source(route_id)
    truth_source = validation_source.get("truth_source")
    if not truth_source:
        return validation_without_truth_source(snapshot, validation_source)

    observed = observations.get(truth_source, {})
    observed_wave = observed.get("wave_height_m")
    target_time = snapshot.get("forecast", {}).get("wave_peak_time")
    predsea_wave = forecast_wave_at(snapshot, target_time)
    baseline_wave = baseline_wave_at(snapshot, target_time)
    marketing = evaluate_marketing_win(predsea_wave, baseline_wave, observed_wave)
    predsea_error = error_delta(predsea_wave, observed_wave)

    validation_status = "validated" if predsea_error is not None else "insufficient_data"
    return {
        "route_id": route_id,
        "route": snapshot.get("route"),
        "truth_source": truth_source,
        "truth_source_name": observed.get("name"),
        "truth_source_suitability": validation_source.get("suitability"),
        "target_time": target_time,
        "predsea_wave_m": predsea_wave,
        "observed_wave_m": observed_wave,
        "observed_at_utc": observed.get("last_sample_utc"),
        "predsea_error_delta_m": predsea_error,
        "baseline_wave_m": baseline_wave,
        "baseline_error_delta_m": marketing["baseline_error_delta_m"],
        "marketing_win": marketing["marketing_win"],
        "marketing_reason": marketing["reason"],
        "validation_status": validation_status,
    }


def validate_route_time_series(snapshot, observation_series, day=None):
    forecast_series = daily_forecast_series(snapshot, day=day)
    aligned = align_time_series(forecast_series, observation_series)
    return {
        "route_id": snapshot.get("route_id"),
        "route": snapshot.get("route"),
        "variable": "significant_wave_height",
        "unit": "m",
        "matched_points": len([row for row in aligned if row.get("observed_wave_m") is not None]),
        "mae_m": mean_absolute_error(aligned),
        "series": aligned,
    }


def validate_route_direction_vectors(snapshot, observation_series, day=None):
    forecast_series = daily_direction_forecast_series(snapshot, day=day)
    aligned = align_direction_vectors(forecast_series, observation_series)
    return {
        "route_id": snapshot.get("route_id"),
        "route": snapshot.get("route"),
        "variable": "wave_from_direction_vectors",
        "unit": "degree",
        "matched_points": len([row for row in aligned if row.get("observed_direction_deg") is not None]),
        "mean_direction_error_deg": mean_direction_error(aligned),
        "series": aligned,
    }


def route_validation_source(route_id):
    try:
        route = route_analysis.load_route(route_id)
    except ValueError:
        return {"truth_source": None, "suitability": "route is not configured"}
    return route.get("validation") or {"truth_source": None, "suitability": "route has no validation source configured"}


def current_validation_source(route_id):
    try:
        route = route_analysis.load_route(route_id)
    except ValueError:
        return {"truth_source": None, "suitability": "route is not configured"}
    return route.get("current_validation") or {
        "truth_source": None,
        "suitability": "route has no current validation source configured",
    }


def fetch_observation_series(validation_source, day=None):
    if not validation_source.get("socib_platform_id"):
        return []
    day = day or date.today().isoformat()
    response = requests.get(
        SOCIB_SERIES_URL,
        params={
            "id_platform": validation_source["socib_platform_id"],
            "id_instrument": validation_source["socib_instrument_id"],
            "id_variable": validation_source["socib_variable_id"],
            "output": "json",
            "sample": 5000,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return observation_series_from_payload(payload, day)


def fetch_direction_observation_series(validation_source, day=None):
    direction_variable_id = validation_source.get("socib_direction_variable_id")
    if not validation_source.get("socib_platform_id") or not direction_variable_id:
        return []
    day = day or date.today().isoformat()
    response = requests.get(
        SOCIB_SERIES_URL,
        params={
            "id_platform": validation_source["socib_platform_id"],
            "id_instrument": validation_source["socib_instrument_id"],
            "id_variable": direction_variable_id,
            "output": "json",
            "sample": 5000,
        },
        timeout=30,
    )
    response.raise_for_status()
    return direction_observation_series_from_payload(response.json(), day)


def fetch_current_speed_observation_series(validation_source, day=None):
    speed_variable_id = validation_source.get("socib_speed_variable_id")
    if not validation_source.get("socib_platform_id") or not speed_variable_id:
        return []
    day = day or date.today().isoformat()
    response = requests.get(
        SOCIB_SERIES_URL,
        params={
            "id_platform": validation_source["socib_platform_id"],
            "id_instrument": validation_source["socib_instrument_id"],
            "id_variable": speed_variable_id,
            "output": "json",
            "sample": 5000,
        },
        timeout=30,
    )
    response.raise_for_status()
    return current_speed_observation_series_from_payload(response.json(), day)


def fetch_current_direction_observation_series(validation_source, day=None):
    direction_variable_id = validation_source.get("socib_direction_variable_id")
    if not validation_source.get("socib_platform_id") or not direction_variable_id:
        return []
    day = day or date.today().isoformat()
    response = requests.get(
        SOCIB_SERIES_URL,
        params={
            "id_platform": validation_source["socib_platform_id"],
            "id_instrument": validation_source["socib_instrument_id"],
            "id_variable": direction_variable_id,
            "output": "json",
            "sample": 5000,
        },
        timeout=30,
    )
    response.raise_for_status()
    return current_direction_observation_series_from_payload(response.json(), day)


def observation_series_from_payload(payload, day):
    rows = []
    for timestamp_ms, value in iter_time_value_pairs(payload):
        if value is None:
            continue
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        if timestamp.date().isoformat() != day:
            continue
        rows.append(
            {
                "time": timestamp.strftime("%H:%M"),
                "observed_wave_m": round(float(value), 2),
                "observed_at_utc": timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            }
        )
    return rows


def direction_observation_series_from_payload(payload, day):
    rows = []
    for timestamp_ms, value in iter_time_value_pairs(payload):
        if value is None:
            continue
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        if timestamp.date().isoformat() != day:
            continue
        rows.append(
            {
                "time": timestamp.strftime("%H:%M"),
                "observed_direction_deg": round(float(value), 1),
                "observed_at_utc": timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            }
        )
    return rows


def current_speed_observation_series_from_payload(payload, day):
    rows = []
    for timestamp_ms, value in iter_time_value_pairs(payload):
        if value is None:
            continue
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        if timestamp.date().isoformat() != day:
            continue
        rows.append(
            {
                "time": timestamp.strftime("%H:%M"),
                "observed_current_mps": round(float(value), 3),
                "observed_at_utc": timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            }
        )
    return rows


def current_direction_observation_series_from_payload(payload, day):
    rows = []
    for timestamp_ms, value in iter_time_value_pairs(payload):
        if value is None:
            continue
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        if timestamp.date().isoformat() != day:
            continue
        rows.append(
            {
                "time": timestamp.strftime("%H:%M"),
                "observed_direction_deg": round(float(value), 1),
                "observed_at_utc": timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            }
        )
    return rows


def iter_time_value_pairs(payload):
    data = payload.get("dataList", {}).get("timeDimensionData", [])
    for item in data:
        if not item:
            continue
        if isinstance(item[0], list):
            for nested in item:
                if len(nested) >= 2:
                    yield nested[0], nested[1]
        elif len(item) >= 2:
            yield item[0], item[1]


def daily_forecast_series(snapshot, day=None):
    rows = []
    previous_minutes = None
    for row in snapshot.get("forecast", {}).get("hourly") or []:
        if day and row.get("time_utc") and not row["time_utc"].startswith(day):
            continue
        time_text = row.get("time")
        wave = row.get("wave_m")
        if time_text is None or wave is None:
            continue
        minutes = minutes_since_midnight(time_text)
        if previous_minutes is not None and minutes < previous_minutes:
            break
        rows.append({"time": time_text, "forecast_wave_m": wave})
        previous_minutes = minutes
    return rows


def daily_direction_forecast_series(snapshot, day=None):
    rows = []
    previous_minutes = None
    for row in snapshot.get("forecast", {}).get("hourly") or []:
        if day and row.get("time_utc") and not row["time_utc"].startswith(day):
            continue
        time_text = row.get("time")
        direction = row.get("wave_direction_deg")
        if time_text is None or direction is None:
            continue
        minutes = minutes_since_midnight(time_text)
        if previous_minutes is not None and minutes < previous_minutes:
            break
        rows.append({"time": time_text, "forecast_direction_deg": direction})
        previous_minutes = minutes
    return rows


def daily_current_speed_forecast_series(snapshot, day=None):
    rows = []
    previous_minutes = None
    for row in snapshot.get("forecast", {}).get("hourly") or []:
        if day and row.get("time_utc") and not row["time_utc"].startswith(day):
            continue
        time_text = row.get("time")
        current = row.get("current_mps")
        if time_text is None or current is None:
            continue
        minutes = minutes_since_midnight(time_text)
        if previous_minutes is not None and minutes < previous_minutes:
            break
        rows.append({"time": time_text, "forecast_current_mps": current})
        previous_minutes = minutes
    return rows


def daily_current_direction_forecast_series(snapshot, day=None):
    rows = []
    previous_minutes = None
    for row in snapshot.get("forecast", {}).get("hourly") or []:
        if day and row.get("time_utc") and not row["time_utc"].startswith(day):
            continue
        time_text = row.get("time")
        direction = row.get("current_direction_deg")
        if time_text is None or direction is None:
            continue
        minutes = minutes_since_midnight(time_text)
        if previous_minutes is not None and minutes < previous_minutes:
            break
        rows.append({"time": time_text, "forecast_direction_deg": direction})
        previous_minutes = minutes
    return rows


def align_time_series(forecast_series, observation_series):
    observations_by_time = {row["time"]: row for row in observation_series}
    aligned = []
    for forecast in forecast_series:
        observed = observations_by_time.get(forecast["time"], {})
        observed_wave = observed.get("observed_wave_m")
        aligned.append(
            {
                "time": forecast["time"],
                "forecast_wave_m": forecast["forecast_wave_m"],
                "observed_wave_m": observed_wave,
                "observed_at_utc": observed.get("observed_at_utc"),
                "error_delta_m": error_delta(forecast["forecast_wave_m"], observed_wave),
            }
        )
    return aligned


def align_direction_vectors(forecast_series, observation_series):
    observations_by_time = {row["time"]: row for row in observation_series}
    aligned = []
    for forecast in forecast_series:
        observed = observations_by_time.get(forecast["time"], {})
        observed_direction = observed.get("observed_direction_deg")
        aligned.append(
            {
                "time": forecast["time"],
                "forecast_direction_deg": forecast["forecast_direction_deg"],
                "observed_direction_deg": observed_direction,
                "observed_at_utc": observed.get("observed_at_utc"),
                "direction_error_deg": circular_error_deg(forecast["forecast_direction_deg"], observed_direction),
            }
        )
    return aligned


def align_current_speed_series(forecast_series, observation_series):
    observations_by_time = {row["time"]: row for row in observation_series}
    aligned = []
    for forecast in forecast_series:
        observed = observations_by_time.get(forecast["time"], {})
        observed_current = observed.get("observed_current_mps")
        aligned.append(
            {
                "time": forecast["time"],
                "forecast_current_mps": forecast["forecast_current_mps"],
                "observed_current_mps": observed_current,
                "observed_at_utc": observed.get("observed_at_utc"),
                "error_delta_mps": error_delta_precise(forecast["forecast_current_mps"], observed_current, digits=3),
            }
        )
    return aligned


def validate_route_current_speed_series(snapshot, observation_series, day=None):
    forecast_series = daily_current_speed_forecast_series(snapshot, day=day)
    aligned = align_current_speed_series(forecast_series, observation_series)
    return {
        "route_id": snapshot.get("route_id"),
        "route": snapshot.get("route"),
        "variable": "surface_current_speed",
        "unit": "m/s",
        "matched_points": len([row for row in aligned if row.get("observed_current_mps") is not None]),
        "mae_mps": mean_absolute_error_key(aligned, "error_delta_mps", digits=3),
        "series": aligned,
    }


def validate_route_current_direction_vectors(snapshot, observation_series, day=None):
    forecast_series = daily_current_direction_forecast_series(snapshot, day=day)
    aligned = align_direction_vectors(forecast_series, observation_series)
    return {
        "route_id": snapshot.get("route_id"),
        "route": snapshot.get("route"),
        "variable": "surface_current_direction_vectors",
        "unit": "degree",
        "matched_points": len([row for row in aligned if row.get("observed_direction_deg") is not None]),
        "mean_direction_error_deg": mean_direction_error(aligned),
        "series": aligned,
    }


def mean_absolute_error(aligned):
    errors = [row["error_delta_m"] for row in aligned if row.get("error_delta_m") is not None]
    if not errors:
        return None
    return round(sum(errors) / len(errors), 2)


def mean_absolute_error_key(aligned, key, digits=2):
    errors = [row[key] for row in aligned if row.get(key) is not None]
    if not errors:
        return None
    return round(sum(errors) / len(errors), digits)


def mean_direction_error(aligned):
    errors = [row["direction_error_deg"] for row in aligned if row.get("direction_error_deg") is not None]
    if not errors:
        return None
    return round(sum(errors) / len(errors), 1)


def circular_error_deg(predicted, observed):
    if predicted is None or observed is None:
        return None
    difference = abs(float(predicted) - float(observed)) % 360
    return round(min(difference, 360 - difference), 1)


def minutes_since_midnight(time_text):
    hour, minute = [int(part) for part in time_text.split(":", 1)]
    return hour * 60 + minute


def render_time_series_png(aligned, route_name, output_path, y_max=2.5):
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1200, 700
    margin_left, margin_right = 90, 50
    margin_top, margin_bottom = 95, 105
    chart_w = width - margin_left - margin_right
    chart_h = height - margin_top - margin_bottom
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (width, height), "#f7fafc")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("Arial.ttf", 30)
        label_font = ImageFont.truetype("Arial.ttf", 18)
        small_font = ImageFont.truetype("Arial.ttf", 14)
    except OSError:
        title_font = label_font = small_font = ImageFont.load_default()

    draw.text((margin_left, 32), f"{route_name} - forecast vs observed wave height", fill="#0f172a", font=title_font)
    if not aligned:
        draw.text((margin_left, margin_top), "No matched time-series data available.", fill="#334155", font=label_font)
        image.save(output_path)
        return output_path

    x0, y0 = margin_left, margin_top
    x1, y1 = margin_left + chart_w, margin_top + chart_h
    draw.rectangle((x0, y0, x1, y1), fill="#ffffff", outline="#cbd5e1")

    for i in range(5):
        y = y1 - (chart_h * i / 4)
        value = y_max * i / 4
        draw.line((x0, y, x1, y), fill="#e2e8f0")
        draw.text((20, y - 8), f"{value:.1f} m", fill="#475569", font=small_font)

    def point(index, value):
        x = x0 + (chart_w * index / max(1, len(aligned) - 1))
        y = y1 - (chart_h * value / y_max)
        return x, y

    forecast_points = [point(i, row["forecast_wave_m"]) for i, row in enumerate(aligned)]
    observed_points = [
        point(i, row["observed_wave_m"])
        for i, row in enumerate(aligned)
        if row.get("observed_wave_m") is not None
    ]
    observed_indexes = [i for i, row in enumerate(aligned) if row.get("observed_wave_m") is not None]

    draw.line(forecast_points, fill="#0891b2", width=4)
    if len(observed_points) > 1:
        draw.line(observed_points, fill="#f97316", width=4)

    for x, y in forecast_points:
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#0891b2")
    for x, y in observed_points:
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#f97316")

    tick_step = max(1, len(aligned) // 8)
    for i, row in enumerate(aligned):
        if i % tick_step == 0 or i == len(aligned) - 1:
            x, _ = point(i, 0)
            draw.text((x - 20, y1 + 18), row["time"], fill="#475569", font=small_font)

    draw.line((margin_left, height - 48, margin_left + 35, height - 48), fill="#0891b2", width=4)
    draw.text((margin_left + 45, height - 58), "Forecast", fill="#0f172a", font=label_font)
    draw.line((margin_left + 180, height - 48, margin_left + 215, height - 48), fill="#f97316", width=4)
    draw.text((margin_left + 225, height - 58), "Observed SOCIB", fill="#0f172a", font=label_font)

    mae = mean_absolute_error(aligned)
    if mae is not None:
        draw.text((width - 250, height - 58), f"MAE: {mae:.2f} m", fill="#0f172a", font=label_font)
    if len(observed_indexes) == 1:
        draw.text((margin_left, height - 82), "Only one observed point matched this forecast series.", fill="#64748b", font=small_font)

    image.save(output_path)
    return output_path


def render_direction_vector_png(aligned, route_name, output_path, variable_label="wave direction", direction_is_from=True):
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1200, 700
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (width, height), "#f7fafc")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("Arial.ttf", 30)
        label_font = ImageFont.truetype("Arial.ttf", 18)
        small_font = ImageFont.truetype("Arial.ttf", 14)
    except OSError:
        title_font = label_font = small_font = ImageFont.load_default()

    draw.text((70, 32), f"{route_name} - {variable_label} vectors", fill="#0f172a", font=title_font)
    subtitle = "One pair per hour. Arrow points toward motion."
    if direction_is_from:
        subtitle = "One pair per hour. Arrow points toward where waves travel from their reported source direction."
    draw.text((70, 70), subtitle, fill="#475569", font=small_font)

    if not aligned:
        draw.text((70, 130), "No direction vector data available.", fill="#334155", font=label_font)
        image.save(output_path)
        return output_path

    panel_left, panel_top = 55, 115
    panel_right, panel_bottom = width - 55, height - 115
    draw.rectangle((panel_left, panel_top, panel_right, panel_bottom), fill="#ffffff", outline="#cbd5e1")

    cols = min(6, max(1, len(aligned)))
    rows = math.ceil(len(aligned) / cols)
    cell_w = (panel_right - panel_left) / cols
    cell_h = (panel_bottom - panel_top) / max(1, rows)
    radius = min(cell_w, cell_h) * 0.24

    for index, row in enumerate(aligned):
        col = index % cols
        grid_row = index // cols
        cx = panel_left + cell_w * col + cell_w / 2
        cy = panel_top + cell_h * grid_row + cell_h / 2 + 8
        draw.text((cx - 24, cy - radius - 34), row["time"], fill="#334155", font=small_font)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline="#e2e8f0", width=1)
        draw.text((cx - 5, cy - radius - 16), "N", fill="#94a3b8", font=small_font)
        draw.text((cx - 5, cy + radius + 2), "S", fill="#94a3b8", font=small_font)
        draw.text((cx + radius + 4, cy - 7), "E", fill="#94a3b8", font=small_font)
        draw.text((cx - radius - 14, cy - 7), "W", fill="#94a3b8", font=small_font)

        draw_direction_arrow(draw, cx - 12, cy, row.get("forecast_direction_deg"), radius * 0.78, "#f97316", direction_is_from=direction_is_from)
        if row.get("observed_direction_deg") is not None:
            draw_direction_arrow(draw, cx + 12, cy, row.get("observed_direction_deg"), radius * 0.78, "#0891b2", direction_is_from=direction_is_from)
        if row.get("direction_error_deg") is not None:
            draw.text((cx - 32, cy + radius + 20), f"err {row['direction_error_deg']:.0f} deg", fill="#64748b", font=small_font)

    draw.line((70, height - 62, 105, height - 62), fill="#f97316", width=4)
    draw.text((115, height - 72), "Forecast", fill="#0f172a", font=label_font)
    draw.line((250, height - 62, 285, height - 62), fill="#0891b2", width=4)
    draw.text((295, height - 72), "Observed SOCIB", fill="#0f172a", font=label_font)
    mean_error = mean_direction_error(aligned)
    if mean_error is not None:
        draw.text((width - 300, height - 72), f"Mean direction error: {mean_error:.1f} deg", fill="#0f172a", font=label_font)

    image.save(output_path)
    return output_path


def draw_direction_arrow(draw, cx, cy, direction_deg, length, color, direction_is_from=True):
    if direction_deg is None:
        return
    # Wave direction is reported as "from"; current direction is already velocity
    # direction. Flip only "from" variables so arrows always point toward motion.
    travel_deg = float(direction_deg)
    if direction_is_from:
        travel_deg = (travel_deg + 180.0) % 360.0
    radians = math.radians(90.0 - travel_deg)
    x2 = cx + length * math.cos(radians)
    y2 = cy - length * math.sin(radians)
    draw.line((cx, cy, x2, y2), fill=color, width=4)
    head_len = 11
    for offset in (145, -145):
        head_angle = radians + math.radians(offset)
        hx = x2 + head_len * math.cos(head_angle)
        hy = y2 - head_len * math.sin(head_angle)
        draw.line((x2, y2, hx, hy), fill=color, width=4)


def validation_without_truth_source(snapshot, validation_source):
    target_time = snapshot.get("forecast", {}).get("wave_peak_time")
    predsea_wave = forecast_wave_at(snapshot, target_time)
    reason = f"No suitable SOCIB wave buoy for this route: {validation_source.get('suitability')}"
    return {
        "route_id": snapshot.get("route_id"),
        "route": snapshot.get("route"),
        "truth_source": None,
        "truth_source_name": None,
        "truth_source_suitability": validation_source.get("suitability"),
        "target_time": target_time,
        "predsea_wave_m": predsea_wave,
        "observed_wave_m": None,
        "observed_at_utc": None,
        "predsea_error_delta_m": None,
        "baseline_wave_m": baseline_wave_at(snapshot, target_time),
        "baseline_error_delta_m": None,
        "marketing_win": False,
        "marketing_reason": reason,
        "validation_status": "no_suitable_truth_source",
    }


def forecast_wave_at(snapshot, target_time):
    forecast = snapshot.get("forecast", {})
    hourly = forecast.get("hourly") or []
    if target_time:
        for row in hourly:
            if row.get("time") == target_time:
                return row.get("wave_m")
    return forecast.get("wave_max_m")


def baseline_wave_at(snapshot, target_time):
    baseline = snapshot.get("baseline_forecast") or snapshot.get("forecast", {}).get("baseline")
    if not baseline:
        return None
    hourly = baseline.get("hourly") or []
    if target_time:
        for row in hourly:
            if row.get("time") == target_time:
                return row.get("wave_m")
    return baseline.get("wave_max_m")


def evaluate_marketing_win(predsea_wave_m, baseline_wave_m, observed_wave_m):
    predsea_error = error_delta(predsea_wave_m, observed_wave_m)
    baseline_error = error_delta(baseline_wave_m, observed_wave_m)
    if predsea_error is None:
        return {
            "marketing_win": False,
            "baseline_error_delta_m": baseline_error,
            "reason": "No observed truth or PredSea forecast available for validation.",
        }
    if baseline_error is None:
        return {
            "marketing_win": False,
            "baseline_error_delta_m": None,
            "reason": "No baseline forecast available; validation is PredSea vs observed only.",
        }
    marketing_win = predsea_error < baseline_error
    comparison = "beats" if marketing_win else "does not beat"
    return {
        "marketing_win": marketing_win,
        "baseline_error_delta_m": baseline_error,
        "reason": (
            f"PredSea error {predsea_error:.1f} m vs baseline error {baseline_error:.1f} m; "
            f"PredSea {comparison} baseline."
        ),
    }


def error_delta(predicted, observed):
    if predicted is None or observed is None:
        return None
    return round(abs(float(predicted) - float(observed)), 1)


def error_delta_precise(predicted, observed, digits=3):
    if predicted is None or observed is None:
        return None
    return round(abs(float(predicted) - float(observed)), digits)


def load_route_snapshots(routes_root=MVP_DATA_DIR / "routes"):
    snapshots = []
    root = Path(routes_root)
    if not root.exists():
        return snapshots
    for snapshot_path in sorted(root.glob("*/daily_snapshot.json")):
        snapshots.append(json.loads(snapshot_path.read_text(encoding="utf-8")))
    return snapshots


def write_validation_outputs(validations, root_dir=VALIDATION_DIR, run_date=None):
    run_date = run_date or date.today().isoformat()
    output_dir = Path(root_dir) / run_date
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "validation_report.json").write_text(
        json.dumps(validations, indent=2),
        encoding="utf-8",
    )
    marketing_lines = marketing_win_lines(validations)
    (output_dir / "marketing_wins.txt").write_text("\n".join(marketing_lines), encoding="utf-8")
    return output_dir


def write_time_series_outputs(time_series_results, output_dir):
    output_dir = Path(output_dir)
    series_dir = output_dir / "time_series"
    series_dir.mkdir(parents=True, exist_ok=True)
    (series_dir / "time_series_report.json").write_text(
        json.dumps(time_series_results, indent=2),
        encoding="utf-8",
    )
    for result in time_series_results:
        if result.get("series"):
            render_time_series_png(
                result["series"],
                result.get("route") or result.get("route_id"),
                series_dir / f"{result.get('route_id')}_wave_timeseries.png",
            )
    return series_dir


def write_direction_vector_outputs(direction_results, output_dir):
    output_dir = Path(output_dir)
    vector_dir = output_dir / "direction_vectors"
    vector_dir.mkdir(parents=True, exist_ok=True)
    (vector_dir / "direction_vector_report.json").write_text(
        json.dumps(direction_results, indent=2),
        encoding="utf-8",
    )
    for result in direction_results:
        if result.get("series"):
            render_direction_vector_png(
                result["series"],
                result.get("route") or result.get("route_id"),
                vector_dir / f"{result.get('route_id')}_wave_direction_vectors.png",
            )
    return vector_dir


def write_current_outputs(current_speed_results, current_direction_results, output_dir):
    output_dir = Path(output_dir)
    current_dir = output_dir / "current_validation"
    current_dir.mkdir(parents=True, exist_ok=True)
    (current_dir / "current_speed_report.json").write_text(
        json.dumps(current_speed_results, indent=2),
        encoding="utf-8",
    )
    (current_dir / "current_direction_vector_report.json").write_text(
        json.dumps(current_direction_results, indent=2),
        encoding="utf-8",
    )
    for result in current_direction_results:
        if result.get("series"):
            render_direction_vector_png(
                result["series"],
                result.get("route") or result.get("route_id"),
                current_dir / f"{result.get('route_id')}_current_direction_vectors.png",
                variable_label="current direction",
                direction_is_from=False,
            )
    return current_dir


def marketing_win_lines(validations):
    lines = []
    for item in validations:
        if item.get("marketing_win"):
            lines.append(f"{item.get('route')}: {item.get('marketing_reason')}")
    if not lines:
        lines.append("No marketing wins with baseline proof in this validation run.")
    return lines


def run_validation(routes_root=MVP_DATA_DIR / "routes", output_root=VALIDATION_DIR):
    observations = load_observations()
    snapshots = load_route_snapshots(routes_root)
    validations = [validate_route_snapshot(snapshot, observations) for snapshot in snapshots]
    output_dir = write_validation_outputs(validations, output_root)
    day = date.today().isoformat()
    time_series_results = []
    direction_results = []
    current_speed_results = []
    current_direction_results = []
    for snapshot in snapshots:
        validation_source = route_validation_source(snapshot.get("route_id"))
        observation_series = fetch_observation_series(validation_source, day) if validation_source.get("truth_source") else []
        time_series_results.append(validate_route_time_series(snapshot, observation_series, day=day))
        direction_series = (
            fetch_direction_observation_series(validation_source, day)
            if validation_source.get("truth_source")
            else []
        )
        direction_results.append(validate_route_direction_vectors(snapshot, direction_series, day=day))
        current_source = current_validation_source(snapshot.get("route_id"))
        current_speed_series = (
            fetch_current_speed_observation_series(current_source, day)
            if current_source.get("truth_source")
            else []
        )
        current_direction_series = (
            fetch_current_direction_observation_series(current_source, day)
            if current_source.get("truth_source")
            else []
        )
        current_speed_results.append(validate_route_current_speed_series(snapshot, current_speed_series, day=day))
        current_direction_results.append(validate_route_current_direction_vectors(snapshot, current_direction_series, day=day))
    write_time_series_outputs(time_series_results, output_dir)
    write_direction_vector_outputs(direction_results, output_dir)
    write_current_outputs(current_speed_results, current_direction_results, output_dir)
    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Validate PredSea route forecasts against SOCIB buoy observations.")
    parser.add_argument("--routes-root", default=str(MVP_DATA_DIR / "routes"), help="Folder containing route snapshots.")
    parser.add_argument("--output-root", default=str(VALIDATION_DIR), help="Folder for validation artifacts.")
    args = parser.parse_args()

    output_dir = run_validation(args.routes_root, args.output_root)
    print(f"Wrote PredSea validation artifacts to {output_dir}/")


if __name__ == "__main__":
    main()
