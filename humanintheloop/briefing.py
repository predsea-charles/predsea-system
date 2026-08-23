import argparse
import copy
import json
from datetime import datetime
from pathlib import Path

import forecast_sanity
import observation_alignment
import decision_engine
import evidence_package
import ingest_observations
import fetch_data
import route_analysis
import source_lineage


OUTPUT_DIR = Path("mvp_data")


def load_observations():
    return load_observation_bundle().get("observations", {})


def load_observation_bundle():
    return ingest_observations.fetch_all_observations(include_puertos=True, include_portus=True)


def build_forecast_summary(route, wind_path=None):
    fetch_data.get_balearic_forecast(dry_run=False)
    return route_analysis.forecast_summary_from_files(
        OUTPUT_DIR / "balearic_waves.nc",
        OUTPUT_DIR / "balearic_currents.nc",
        wind_path=wind_path,
        route=route,
    )


def route_output_dir(root, route):
    return Path(root) / "routes" / route["id"]


def write_outputs(snapshot, output_dir=OUTPUT_DIR, question=None, location_label="Palma Marina", current_time=None, route=None):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    snapshot = _attach_source_summary(snapshot)
    briefing = build_daily_briefing_summary(snapshot)
    snapshot = copy.deepcopy(snapshot)
    snapshot["daily_briefing"] = briefing
    (output_path / "daily_snapshot.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    (output_path / "daily_briefing.json").write_text(json.dumps(briefing, indent=2), encoding="utf-8")
    if route or snapshot.get("route_id"):
        route = route or route_analysis.load_route(snapshot["route_id"])
        evidence = evidence_package.build_route_evidence_package(snapshot, route)
        (output_path / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if question:
        decision = decision_engine.answer_question(
            question,
            snapshot,
            location_label=location_label,
            current_time=current_time,
        )
        (output_path / "decision_answer.txt").write_text(decision["answer"], encoding="utf-8")


def _attach_source_summary(snapshot):
    enriched = copy.deepcopy(snapshot)
    summary = source_lineage.summarize_sources(
        snapshot=enriched,
        observations=enriched.get("observations"),
        source_inventory=enriched.get("source_inventory"),
        data_lineage=enriched.get("data_lineage"),
    )
    enriched["source_summary"] = summary
    enriched.setdefault("data_lineage", {})
    enriched["data_lineage"]["source_summary"] = summary
    return enriched


def build_daily_briefing_summary(snapshot):
    forecast = snapshot.get("forecast", {})
    recommendation = snapshot.get("recommendation", {})
    alignment = snapshot.get("observation_alignment") or observation_alignment.compute_observation_alignment(snapshot)
    sanity = snapshot.get("forecast_sanity") or forecast_sanity.forecast_sanity(forecast)
    created_at = snapshot.get("created_at_utc")
    return {
        "summary_type": "daily_marine_briefing",
        "valid_for": "24h",
        "issued_at_utc": created_at,
        "issued_at_local": _to_local_time(created_at),
        "wind_speed_kn": forecast.get("wind_speed_kn"),
        "wind_direction_deg": forecast.get("wind_direction_deg"),
        "wind_gust_kn": forecast.get("wind_gust_kn"),
        "wind_trend": _trend_text(forecast, "wind_speed_kn"),
        "wave_trend": _trend_text(forecast, "wave_m"),
        "swell_direction": forecast.get("wave_peak_direction_deg"),
        "current_trend": _trend_text(forecast, "current_kn"),
        "thunderstorm_probability": forecast.get("thunderstorm_probability"),
        "sunrise": forecast.get("sunrise_local"),
        "sunset": forecast.get("sunset_local"),
        "moon": forecast.get("moon_phase"),
        "confidence": recommendation.get("confidence", "Low").capitalize(),
        "watch_out": recommendation.get("watch_out"),
        "observation_alignment": alignment,
        "forecast_sanity": sanity,
    }


def _to_local_time(value):
    if not value:
        return None
    return value.replace(" UTC", " LT")


def _trend_text(forecast, key):
    hourly = forecast.get("hourly") or []
    values = [row.get(key) for row in hourly]
    values = [value for value in values if isinstance(value, (int, float))]
    if len(values) < 2:
        return "steady"
    
    threshold = 0.2
    if "wind" in key:
        threshold = 3.0
    elif "current" in key:
        threshold = 0.2
        
    if values[-1] > values[0] + threshold:
        return "building"
    if values[-1] < values[0] - threshold:
        return "easing"
    return "steady"


def main():
    parser = argparse.ArgumentParser(description="Generate PredSea briefing artifacts.")
    parser.add_argument("--route", default=route_analysis.DEFAULT_ROUTE_ID, help="Route ID from routes.json.")
    parser.add_argument(
        "--vessel-class",
        default="medium",
        choices=sorted(route_analysis.VESSEL_PROFILES),
        help="Vessel size class for recommendation thresholds.",
    )
    parser.add_argument("--list-routes", action="store_true", help="Print available routes and exit.")
    parser.add_argument("--question", help="Captain question to answer from the generated snapshot.")
    parser.add_argument("--location-label", default="Palma Marina", help="Human-friendly label for shared location demos.")
    parser.add_argument("--current-time", help="Override local HH:MM used for decision timing, useful for demos.")
    args = parser.parse_args()

    if args.list_routes:
        for route_id, route in sorted(route_analysis.load_routes().items()):
            print(f"{route_id}: {route['name']}")
        return

    route = route_analysis.load_route(args.route)
    observations = load_observations()
    forecast = build_forecast_summary(route)
    snapshot = route_analysis.build_route_snapshot(
        observations,
        forecast,
        route=route,
        vessel_class=args.vessel_class,
    )
    write_outputs(
        snapshot,
        output_dir=route_output_dir(OUTPUT_DIR, route),
        question=args.question,
        location_label=args.location_label,
        current_time=args.current_time or datetime.now().strftime("%H:%M"),
        route=route,
    )
    print(f"Wrote PredSea briefing artifacts to {route_output_dir(OUTPUT_DIR, route)}/")


if __name__ == "__main__":
    main()
