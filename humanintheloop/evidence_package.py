from datetime import datetime

import source_lineage


SCHEMA_VERSION = "predsea.evidence.v1"


def build_route_evidence_package(snapshot, route):
    forecast = snapshot.get("forecast", {})
    recommendation = snapshot.get("recommendation", {})
    observations = snapshot.get("observations", {})
    validation = route.get("validation", {})
    current_validation = route.get("current_validation", {})

    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_package_id": evidence_package_id(snapshot, route),
        "data_lineage": data_lineage(snapshot, observations),
        "subject": {
            "type": "route",
            "id": route["id"],
            "name": route["name"],
            "note": route.get("route_note"),
            "origin": route.get("origin"),
            "destination": route.get("destination"),
            "sample_points": route.get("sample_points", []),
        },
        "created_at_utc": snapshot.get("created_at_utc"),
        "models": {
            "waves": "copernicus_med_forecast",
            "currents": "copernicus_med_forecast",
        },
        "observations": {
            "sources": sorted(observations),
            "records": observations,
        },
        "forecast": {
            "sampling_method": forecast.get("sampling_method"),
            "route_segments": forecast.get("route_segments", {}),
            "variables": {
                "wave_height_m": {
                    "min": forecast.get("wave_min_m"),
                    "max": forecast.get("wave_max_m"),
                    "peak_time": forecast.get("wave_peak_time"),
                    "peak_direction_deg": forecast.get("wave_peak_direction_deg"),
                    "route_bearing_deg": forecast.get("route_bearing_deg"),
                    "peak_relative_angle_deg": forecast.get("wave_peak_relative_angle_deg"),
                    "peak_sea_state": forecast.get("wave_peak_sea_state"),
                    "hourly": [
                        {
                            key: row[key]
                            for key in (
                                "time",
                                "time_utc",
                                "wave_m",
                                "wave_direction_deg",
                                "wave_relative_angle_deg",
                                "wave_sea_state",
                            )
                            if key in row
                        }
                        for row in forecast.get("hourly", [])
                    ],
                },
                "swell_1": wave_component_forecast(forecast, "swell_1"),
                "swell_2": wave_component_forecast(forecast, "swell_2"),
                "wind_wave": wave_component_forecast(forecast, "wind_wave"),
                "current_speed_kn": {
                    "max": forecast.get("current_max_kn"),
                    "peak_time": forecast.get("current_peak_time"),
                    "hourly": [
                        {
                            key: row[key]
                            for key in ("time", "time_utc", "current_kn", "current_direction_deg")
                            if key in row
                        }
                        for row in forecast.get("hourly", [])
                    ],
                },
                "wind_speed_kn": {
                    "mean": forecast.get("wind_speed_kn"),
                    "gust_max": forecast.get("wind_gust_kn"),
                    "direction_deg": forecast.get("wind_direction_deg"),
                    "hourly": [
                        {
                            key: row[key]
                            for key in ("time", "time_utc", "wind_speed_kn", "wind_direction_deg", "wind_gust_kn")
                            if key in row
                        }
                        for row in forecast.get("hourly", [])
                    ],
                },
            },
        },
        "operational_interpretation": {
            "status": recommendation.get("vessel_severity", "unknown"),
            "best_window": recommendation.get("best_window"),
            "watch_out": recommendation.get("watch_out"),
            "vessel_advice": recommendation.get("vessel_advice"),
            "confidence": recommendation.get("confidence", "low"),
        },
        "data_quality": {
            "nearest_wave_truth_source": validation.get("truth_source"),
            "wave_truth_suitability": validation.get("suitability"),
            "nearest_current_truth_source": current_validation.get("truth_source"),
            "current_truth_suitability": current_validation.get("suitability"),
            "buoy_truth_available": bool(validation.get("truth_source") or current_validation.get("truth_source")),
            "observation_alignment": snapshot.get("observation_alignment") or {},
            "forecast_sanity": snapshot.get("forecast_sanity") or {},
        },
        "daily_briefing": snapshot.get("daily_briefing"),
        "decision_context": snapshot,
    }


def evidence_package_id(snapshot, route):
    if snapshot.get("evidence_package_id"):
        return snapshot["evidence_package_id"]

    route_id = snapshot.get("route_id") or route.get("id") or "route"
    created_at = snapshot.get("created_at_utc") or "unknown"
    compact_time = compact_timestamp(created_at)
    return f"{route_id}_{compact_time}"


def compact_timestamp(value):
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M:%S UTC"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%dT%H%M%SZ")
        except ValueError:
            pass
    return (
        text.replace(" UTC", "Z")
        .replace("-", "")
        .replace(":", "")
        .replace(" ", "T")
    )


def data_lineage(snapshot, observations):
    if snapshot.get("data_lineage"):
        lineage = dict(snapshot["data_lineage"])
        if (
            snapshot.get("source_summary")
            or snapshot.get("source_inventory")
            or lineage.get("source_summary")
        ):
            lineage.setdefault("source_summary", source_lineage.summarize_sources(snapshot=snapshot, observations=observations))
        return lineage

    lineage = {
        "wind_forecast": {
            "source": None,
            "resolution_km": None,
            "status": "not_configured",
        },
        "ocean_forecast": {
            "source": "copernicus_med",
            "resolution_km": 4.0,
            "status": "active",
        },
        "ground_truth_validation": {
            "source": "puertos_observations" if observations else None,
            "status": "matched_successfully" if observations else "unavailable",
        },
    }
    if snapshot.get("source_summary") or snapshot.get("source_inventory"):
        lineage["source_summary"] = source_lineage.summarize_sources(snapshot=snapshot, observations=observations)
    return lineage


def wave_component_forecast(forecast, component_name):
    return {
        "height_m": forecast.get(f"{component_name}_height_m"),
        "direction_deg": forecast.get(f"{component_name}_direction_deg"),
        "hourly": [
            {
                key: row[key]
                for key in (
                    "time",
                    "time_utc",
                    f"{component_name}_height_m",
                    f"{component_name}_direction_deg",
                )
                if key in row
            }
            for row in forecast.get("hourly", [])
            if f"{component_name}_height_m" in row or f"{component_name}_direction_deg" in row
        ],
    }


def snapshot_from_evidence(package):
    return package.get("decision_context", package)
