from __future__ import annotations

from math import cos, degrees, radians, sin, sqrt, atan2
from pathlib import Path
from typing import Any

from processing.mariner_interpreter import get_captain_summary, MPS_TO_KNOTS
from processing.nemo_interpreter import get_nemo_summary
from processing.swan_interpreter import get_swan_summary


COMFORT_LEVELS = {
    0: "comfortable",
    1: "moderate",
    2: "rough",
    3: "high_risk",
}


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle bearing from point 1 to point 2."""
    d_lon = radians(lon2 - lon1)
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    y = sin(d_lon) * cos(lat2_rad)
    x = cos(lat1_rad) * sin(lat2_rad) - sin(lat1_rad) * cos(lat2_rad) * cos(d_lon)
    return degrees(atan2(y, x)) % 360


def get_comfort_level(wave_height: float, current_speed_knots: float) -> str:
    """Classify the nautical comfort status based on wave heights and current velocities."""
    # Wave height grades
    if wave_height < 0.8:
        wave_score = 0
    elif wave_height <= 1.5:
        wave_score = 1
    elif wave_height <= 2.2:
        wave_score = 2
    else:
        wave_score = 3

    # Current speed grades
    if current_speed_knots < 0.5:
        current_score = 0
    elif current_speed_knots <= 1.2:
        current_score = 1
    elif current_speed_knots <= 2.0:
        current_score = 2
    else:
        current_score = 3

    return COMFORT_LEVELS[max(wave_score, current_score)]


def calculate_fuel_penalty(
    wave_height: float,
    uo_mps: float,
    vo_mps: float,
    travel_bearing: float | None,
) -> float:
    """Calculate overall fuel penalty impact based on currents and waves."""
    # 1. Opposing current headwind penalty
    opposing_current_penalty = 0.0
    if travel_bearing is not None:
        # Convert bearing to radians and compute direction unit vector
        bearing_rad = radians(travel_bearing)
        travel_u = sin(bearing_rad)
        travel_v = cos(bearing_rad)

        # Dot product of current velocity vector and travel vector
        # Positive projection means currents assist travel, negative means they oppose
        current_along_travel = uo_mps * travel_u + vo_mps * travel_v
        
        if current_along_travel < 0:
            opposing_current_knots = -current_along_travel * MPS_TO_KNOTS
            # Cap head current penalty at +30% for 2.0 knots or more opposing current
            opposing_current_penalty = min(0.30, max(0.0, (opposing_current_knots / 2.0) * 0.30))

    # 2. Wave resistance penalty
    # Cap wave resistance penalty at +50% for wave heights of 3.0 meters or more
    wave_resistance_penalty = min(0.50, max(0.0, (wave_height / 3.0) * 0.50))

    # Total penalty = 1.0 + opposing_current_penalty + wave_resistance_penalty
    return round(1.0 + opposing_current_penalty + wave_resistance_penalty, 3)


def fuse_marine_conditions(
    lat: float,
    lon: float,
    time: str | None,
    wrf_path: str | Path,
    nemo_path: str | Path,
    swan_path: str | Path,
    travel_bearing: float | None = None,
) -> dict[str, Any]:
    """Fuse WRF atmospheric, NEMO physical currents, and SWAN waves into a single coordinate point summary."""
    wrf_sum = get_captain_summary(lat, lon, time, wrfout_path=wrf_path)
    nemo_sum = get_nemo_summary(lat, lon, time, nemo_path=nemo_path)
    swan_sum = get_swan_summary(lat, lon, time, swan_path=swan_path)

    wave_h = swan_sum["significant_wave_height_m"]
    current_spd = nemo_sum["current_speed_knots"]
    uo = nemo_sum["metrics"]["uo_mps"]
    vo = nemo_sum["metrics"]["vo_mps"]

    comfort = get_comfort_level(wave_h, current_spd)
    fuel = calculate_fuel_penalty(wave_h, uo, vo, travel_bearing)

    # Narrative summary
    summary_text = (
        f"Sea conditions are classified as {comfort.upper()}. "
        f"Winds are {wrf_sum['wind_knots']} kt from {wrf_sum['direction']}. "
        f"Waves are {wave_h}m at {swan_sum['peak_wave_period_s'] or 'N/A'}s "
        f"from {swan_sum['wave_direction_cardinal']}. "
        f"Surface currents are running at {current_spd} kt towards {nemo_sum['current_direction']}."
    )

    return {
        "latitude": lat,
        "longitude": lon,
        "time": time,
        "comfort_status": comfort,
        "fuel_penalty": fuel,
        "captain_summary": summary_text,
        "wind": {
            "speed_knots": wrf_sum["wind_knots"],
            "direction": wrf_sum["direction"],
        },
        "currents": {
            "speed_knots": current_spd,
            "direction": nemo_sum["current_direction"],
            "uo_mps": uo,
            "vo_mps": vo,
            "sea_surface_height_m": nemo_sum["metrics"]["sea_surface_height_m"],
            "sea_surface_temperature_c": nemo_sum["metrics"]["sea_surface_temperature_c"],
        },
        "waves": {
            "significant_height_m": wave_h,
            "peak_period_s": swan_sum["peak_wave_period_s"],
            "direction_cardinal": swan_sum["wave_direction_cardinal"],
        },
    }


def fuse_route_conditions(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    time: str | None,
    wrf_path: str | Path,
    nemo_path: str | Path,
    swan_path: str | Path,
    samples: int = 8,
) -> dict[str, Any]:
    """Fuse and analyze ocean and wind layers segment-by-segment along a routing corridor."""
    from processing.mariner_interpreter import sample_route_points

    route_points = sample_route_points(start_lat, start_lon, end_lat, end_lon, samples)
    bearing = calculate_bearing(start_lat, start_lon, end_lat, end_lon)

    segment_summaries = []
    for pt in route_points:
        summary = fuse_marine_conditions(
            lat=pt["lat"],
            lon=pt["lon"],
            time=time,
            wrf_path=wrf_path,
            nemo_path=nemo_path,
            swan_path=swan_path,
            travel_bearing=bearing,
        )
        segment_summaries.append(summary)

    # Risk ranking helper
    comfort_rank = {"comfortable": 0, "moderate": 1, "rough": 2, "high_risk": 3}
    worst = max(
        segment_summaries,
        key=lambda s: (
            comfort_rank.get(s["comfort_status"], 0),
            s["waves"]["significant_height_m"],
            s["currents"]["speed_knots"],
        ),
    )

    avg_fuel_penalty = round(sum(s["fuel_penalty"] for s in segment_summaries) / len(segment_summaries), 3)

    summary_guidance = (
        f"Route passage is {worst['comfort_status'].upper()} at worst. "
        f"Highest sampled waves are {worst['waves']['significant_height_m']}m and max currents are {worst['currents']['speed_knots']} kt. "
        f"Expected average fuel penalty is +{round((avg_fuel_penalty - 1.0) * 100, 1)}%."
    )

    return {
        "worst_segment": worst,
        "comfort_status": worst["comfort_status"],
        "average_fuel_penalty": avg_fuel_penalty,
        "samples": segment_summaries,
        "sample_count": len(segment_summaries),
        "route_summary": summary_guidance,
        "bearing_degrees": round(bearing, 1),
    }
