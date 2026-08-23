import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

import validation_engine


PREDICTIONS_DIR = Path("../predictions")
OUTPUT_DIR = Path("mvp_data/validation/predictions_scalar_timeseries")


def parse_time_to_hour(time_text):
    timestamp = datetime.strptime(time_text, "%H:%M")
    return timestamp.hour + timestamp.minute / 60


def hourly_average(rows, value_key):
    buckets = defaultdict(list)
    for row in rows:
        value = row.get(value_key)
        if value is None:
            continue
        buckets[row["time"][:2] + ":00"].append(float(value))
    return {
        time_text: sum(values) / len(values)
        for time_text, values in buckets.items()
        if values
    }


def forecast_wave_series(snapshot, day):
    rows = validation_engine.daily_forecast_series(snapshot, day=day)
    return {row["time"]: row["forecast_wave_m"] for row in rows}


def forecast_current_series(snapshot, day):
    rows = validation_engine.daily_current_speed_forecast_series(snapshot, day=day)
    return {row["time"]: row["forecast_current_mps"] for row in rows}


def fetch_wave_observations(source, day):
    rows = validation_engine.fetch_observation_series(source, day)
    return hourly_average(rows, "observed_wave_m")


def fetch_current_observations(source, day):
    rows = validation_engine.fetch_current_speed_observation_series(source, day)
    return hourly_average(rows, "observed_current_mps")


def draw_line_plot(title, y_label, forecast, observed, output_path, y_limit=None):
    times = sorted(set(forecast) | set(observed), key=parse_time_to_hour)
    if not times:
        return None

    x = [parse_time_to_hour(time_text) for time_text in times]
    forecast_y = [forecast.get(time_text) for time_text in times]
    observed_y = [observed.get(time_text) for time_text in times]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(13, 6.5), dpi=180)
    plt.plot(x, forecast_y, color="#0891b2", linewidth=2.8, marker="o", label="Forecast")
    plt.plot(x, observed_y, color="#f97316", linewidth=2.8, marker="o", label="SOCIB observed")
    plt.title(title, fontsize=16, loc="left")
    plt.ylabel(y_label)
    plt.xlabel("UTC hour")
    plt.xticks(range(0, 24, 2), [f"{hour:02d}:00" for hour in range(0, 24, 2)])
    plt.xlim(0, 23)
    if y_limit:
        plt.ylim(*y_limit)
    plt.grid(True, color="#dbe3ea", linewidth=0.8)
    plt.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    return output_path


def load_snapshot(day_dir, route_id):
    path = day_dir / route_id / "daily_snapshot.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    generated = []
    cached_wave_obs = {}
    cached_current_obs = {}

    for day_dir in sorted(PREDICTIONS_DIR.iterdir()):
        if not day_dir.is_dir() or not day_dir.name.startswith("2026-"):
            continue
        day = day_dir.name
        for snapshot_path in sorted(day_dir.glob("*/daily_snapshot.json")):
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            route_id = snapshot["route_id"]
            route_name = snapshot["route"]

            wave_source = validation_engine.route_validation_source(route_id)
            if wave_source.get("truth_source"):
                source_key = ("wave", day, wave_source["socib_platform_id"], wave_source["socib_instrument_id"])
                if source_key not in cached_wave_obs:
                    cached_wave_obs[source_key] = fetch_wave_observations(wave_source, day)
                forecast = forecast_wave_series(snapshot, day)
                observed = cached_wave_obs[source_key]
                output_path = OUTPUT_DIR / day / f"{route_id}_wave_height_forecast_vs_socib.png"
                result = draw_line_plot(
                    f"{route_name} - wave height forecast vs SOCIB ({day})",
                    "Significant wave height (m)",
                    forecast,
                    observed,
                    output_path,
                    y_limit=(0, 2.5),
                )
                if result:
                    generated.append(str(result))

            current_source = validation_engine.current_validation_source(route_id)
            if current_source.get("truth_source"):
                source_key = ("current", day, current_source["socib_platform_id"], current_source["socib_instrument_id"])
                if source_key not in cached_current_obs:
                    cached_current_obs[source_key] = fetch_current_observations(current_source, day)
                forecast = forecast_current_series(snapshot, day)
                observed = cached_current_obs[source_key]
                output_path = OUTPUT_DIR / day / f"{route_id}_current_speed_forecast_vs_socib.png"
                result = draw_line_plot(
                    f"{route_name} - current speed forecast vs SOCIB ({day})",
                    "Surface current speed (m/s)",
                    forecast,
                    observed,
                    output_path,
                    y_limit=(0, 0.7),
                )
                if result:
                    generated.append(str(result))

    manifest = {
        "generated_count": len(generated),
        "outputs": generated,
        "note": "Wave direction and current direction are directional variables; use vector validation plots for those.",
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {len(generated)} scalar validation plots in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
