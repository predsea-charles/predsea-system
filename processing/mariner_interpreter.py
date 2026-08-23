from __future__ import annotations

import heapq
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


MPS_TO_KNOTS = 1.9438444924406
EARTH_RADIUS_KM = 6371.0
DEFAULT_WRFOUT_PATH = Path("processing/fixtures/wrfout_d03_sample.nc")
CARDINAL_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
CONDITION_RANK = {
    "Favorable": 0,
    "Moderate Wind": 1,
    "Strong Wind Advisory": 2,
    "Gale Warning": 3,
}


class MarinerInterpreterError(ValueError):
    """Raised when WRF output cannot produce captain-ready guidance."""


def get_captain_summary(
    lat: float,
    lon: float,
    time: str | None,
    wrfout_path: str | Path = DEFAULT_WRFOUT_PATH,
) -> dict[str, Any]:
    """Return LLM-ready captain guidance for a point in a WRF output file."""

    path = Path(wrfout_path)
    with xr.open_dataset(path) as dataset:
        time_index = _select_time_index(dataset, time)
        grid = _nearest_grid_point_from_dataset(dataset, lat, lon, time_index)
        values = _extract_point_values(dataset, grid["grid_j"], grid["grid_i"], time_index)

    wind_knots = round(sqrt(values["u10"] ** 2 + values["v10"] ** 2) * MPS_TO_KNOTS)
    direction = wind_direction_cardinal(values["u10"], values["v10"])
    gust_factor = round(_gust_factor(wind_knots, values["terrain_m"]), 2)
    stability = _sea_state_stability(wind_knots, gust_factor, values["terrain_m"])
    condition = _condition(wind_knots, gust_factor)

    return {
        "condition": condition,
        "wind_knots": int(wind_knots),
        "direction": direction,
        "gust_factor": gust_factor,
        "sea_state_stability": stability,
        "risk_assessment": _risk_assessment(condition, direction, wind_knots, gust_factor, values["terrain_m"]),
        "source": str(path),
        "location": {
            "requested": {"lat": float(lat), "lon": float(lon)},
            "nearest_grid": grid,
        },
        "metrics": {
            "u10_mps": round(values["u10"], 2),
            "v10_mps": round(values["v10"], 2),
            "temperature_c": round(values["temperature_k"] - 273.15, 2),
            "pressure_hpa": round(values["pressure_pa"] / 100.0, 2),
            "terrain_m": round(values["terrain_m"], 1),
            "rain_total_mm": round(values["rain_total_mm"], 2),
        },
    }


def nearest_grid_point(wrfout_path: str | Path, lat: float, lon: float) -> dict[str, Any]:
    with xr.open_dataset(wrfout_path) as dataset:
        return _nearest_grid_point_from_dataset(dataset, lat, lon, time_index=0)


def sample_route_points(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    samples: int = 8,
) -> list[dict[str, float]]:
    if samples < 2:
        raise MarinerInterpreterError("Route sampling requires at least two samples.")

    points = []
    for index in range(samples):
        fraction = index / (samples - 1)
        points.append(
            {
                "lat": round(start_lat + (end_lat - start_lat) * fraction, 6),
                "lon": round(start_lon + (end_lon - start_lon) * fraction, 6),
            }
        )
    return points


def get_route_summary(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    time: str | None,
    wrfout_path: str | Path = DEFAULT_WRFOUT_PATH,
    samples: int = 8,
) -> dict[str, Any]:
    route_points = sample_route_points(start_lat, start_lon, end_lat, end_lon, samples)
    sample_summaries = [
        get_captain_summary(
            lat=point["lat"],
            lon=point["lon"],
            time=time,
            wrfout_path=wrfout_path,
        )
        for point in route_points
    ]
    worst = max(
        sample_summaries,
        key=lambda summary: (
            CONDITION_RANK.get(summary["condition"], -1),
            summary["wind_knots"] * summary["gust_factor"],
            summary["wind_knots"],
        ),
    )

    return {
        "condition": worst["condition"],
        "route_summary": _route_assessment(worst, len(sample_summaries)),
        "worst_point": worst,
        "samples": sample_summaries,
        "sample_count": len(sample_summaries),
        "source": str(wrfout_path),
    }


def get_optimal_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    time: str | None,
    wrfout_path: str | Path = DEFAULT_WRFOUT_PATH,
    cost_field: str = "wind",
) -> dict[str, Any]:
    if cost_field != "wind":
        raise MarinerInterpreterError(f"Unsupported cost_field {cost_field!r}. Supported: 'wind'.")

    path = Path(wrfout_path)
    with xr.open_dataset(path) as dataset:
        time_index = _select_time_index(dataset, time)
        start = _nearest_grid_point_from_dataset(dataset, start_lat, start_lon, time_index)
        end = _nearest_grid_point_from_dataset(dataset, end_lat, end_lon, time_index)
        wind_knots = _wind_speed_grid(dataset, time_index)
        lats = _time_slice(dataset["XLAT"], time_index).values
        lons = _time_slice(dataset["XLONG"], time_index).values
        grid_path, total_cost = _dijkstra_grid_path(
            wind_knots=wind_knots,
            lats=lats,
            lons=lons,
            start=(start["grid_j"], start["grid_i"]),
            end=(end["grid_j"], end["grid_i"]),
        )
        points = [_route_point_from_grid(dataset, grid_j, grid_i, time_index, wind_knots) for grid_j, grid_i in grid_path]

    worst = max(points, key=lambda point: (point["wind_knots"] * point["gust_factor"], point["wind_knots"]))
    route_distance_km = _path_distance_km(points)

    return {
        "route_type": "lowest_wind",
        "cost_field": cost_field,
        "total_cost": round(total_cost, 2),
        "route_distance_km": round(route_distance_km, 2),
        "start": {"requested": {"lat": start_lat, "lon": start_lon}, "nearest_grid": start},
        "end": {"requested": {"lat": end_lat, "lon": end_lon}, "nearest_grid": end},
        "points": points,
        "point_count": len(points),
        "worst_point": worst,
        "summary": (
            f"Computed a lowest-wind route across {len(points)} grid steps. "
            f"Worst point is {worst['wind_knots']} kt {worst['direction']} near "
            f"{worst['lat']:.4f}, {worst['lon']:.4f}."
        ),
        "source": str(path),
    }


def compare_optimal_routes(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    time: str | None,
    wrfout_paths: list[str | Path],
    cost_field: str = "wind",
) -> dict[str, Any]:
    routes = []
    for wrfout_path in wrfout_paths:
        route = get_optimal_route(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            time=time,
            wrfout_path=wrfout_path,
            cost_field=cost_field,
        )
        route["domain"] = _domain_label(Path(wrfout_path))
        routes.append(route)

    shortest = min(routes, key=lambda route: route["route_distance_km"])
    longest = max(routes, key=lambda route: route["route_distance_km"])

    return {
        "cost_field": cost_field,
        "route_count": len(routes),
        "routes": routes,
        "shortest_route": {
            "domain": shortest["domain"],
            "route_distance_km": shortest["route_distance_km"],
            "total_cost": shortest["total_cost"],
        },
        "longest_route": {
            "domain": longest["domain"],
            "route_distance_km": longest["route_distance_km"],
            "total_cost": longest["total_cost"],
        },
        "distance_spread_km": round(longest["route_distance_km"] - shortest["route_distance_km"], 2),
    }


def wind_direction_cardinal(u: float, v: float) -> str:
    """Return meteorological direction, where N means wind coming from north."""

    direction_degrees = (degrees(atan2(-u, -v)) + 360.0) % 360.0
    index = int((direction_degrees + 22.5) // 45.0) % len(CARDINAL_DIRECTIONS)
    return CARDINAL_DIRECTIONS[index]


def _select_time_index(dataset: xr.Dataset, time: str | None) -> int:
    if "Time" not in dataset.sizes:
        return 0
    if time is None or dataset.sizes["Time"] == 1:
        return 0
    if "XTIME" not in dataset:
        raise MarinerInterpreterError("Cannot select by time because WRF output has no XTIME coordinate.")

    target = np.datetime64(time)
    values = dataset["XTIME"].values
    if np.issubdtype(values.dtype, np.datetime64):
        deltas = np.abs(values - target)
        return int(deltas.argmin())
    return 0


def _nearest_grid_point_from_dataset(dataset: xr.Dataset, lat: float, lon: float, time_index: int) -> dict[str, Any]:
    _require_variables(dataset, ["XLAT", "XLONG"])
    lats = _time_slice(dataset["XLAT"], time_index)
    lons = _time_slice(dataset["XLONG"], time_index)
    distance = (lats - lat) ** 2 + ((lons - lon) * np.cos(np.deg2rad(lat))) ** 2
    grid_j, grid_i = np.unravel_index(int(np.argmin(distance.values)), distance.shape)
    return {
        "lat": float(lats.values[grid_j, grid_i]),
        "lon": float(lons.values[grid_j, grid_i]),
        "grid_i": int(grid_i),
        "grid_j": int(grid_j),
    }


def _extract_point_values(dataset: xr.Dataset, grid_j: int, grid_i: int, time_index: int) -> dict[str, float]:
    _require_variables(dataset, ["U10", "V10", "T2", "PSFC", "HGT"])

    rainc = _point_value(dataset, "RAINC", grid_j, grid_i, time_index, default=0.0)
    rainnc = _point_value(dataset, "RAINNC", grid_j, grid_i, time_index, default=0.0)
    return {
        "u10": _point_value(dataset, "U10", grid_j, grid_i, time_index),
        "v10": _point_value(dataset, "V10", grid_j, grid_i, time_index),
        "temperature_k": _point_value(dataset, "T2", grid_j, grid_i, time_index),
        "pressure_pa": _point_value(dataset, "PSFC", grid_j, grid_i, time_index),
        "terrain_m": _point_value(dataset, "HGT", grid_j, grid_i, time_index),
        "rain_total_mm": rainc + rainnc,
    }


def _point_value(
    dataset: xr.Dataset,
    name: str,
    grid_j: int,
    grid_i: int,
    time_index: int,
    default: float | None = None,
) -> float:
    if name not in dataset:
        if default is None:
            raise MarinerInterpreterError(f"WRF output is missing required variable {name!r}.")
        return default
    variable = _time_slice(dataset[name], time_index)
    return float(variable.values[grid_j, grid_i])


def _time_slice(variable: xr.DataArray, time_index: int) -> xr.DataArray:
    if "Time" in variable.dims:
        return variable.isel(Time=time_index)
    return variable


def _require_variables(dataset: xr.Dataset, names: list[str]) -> None:
    missing = [name for name in names if name not in dataset]
    if missing:
        raise MarinerInterpreterError(f"WRF output is missing required variable(s): {', '.join(missing)}")


def _gust_factor(wind_knots: float, terrain_m: float) -> float:
    terrain_boost = min(max(terrain_m, 0.0) / 1000.0, 0.35)
    wind_boost = 0.1 if wind_knots >= 25 else 0.0
    return 1.15 + terrain_boost + wind_boost


def _sea_state_stability(wind_knots: float, gust_factor: float, terrain_m: float) -> str:
    if wind_knots >= 30 or gust_factor >= 1.45:
        return "unstable"
    if wind_knots >= 18 or terrain_m >= 250:
        return "channel-sensitive"
    return "stable"


def _condition(wind_knots: float, gust_factor: float) -> str:
    gust_knots = wind_knots * gust_factor
    if wind_knots >= 34 or gust_knots >= 40:
        return "Gale Warning"
    if wind_knots >= 22 or gust_knots >= 30:
        return "Strong Wind Advisory"
    if wind_knots >= 16:
        return "Moderate Wind"
    return "Favorable"


def _risk_assessment(
    condition: str,
    direction: str,
    wind_knots: int,
    gust_factor: float,
    terrain_m: float,
) -> str:
    if condition == "Gale Warning":
        return (
            f"{condition}: {wind_knots} kt {direction} flow with gust factor {gust_factor}. "
            "High risk of acceleration zones and confused seas near exposed Balearic channels."
        )
    if condition == "Strong Wind Advisory":
        terrain_note = " Terrain-driven gusts are possible near cliffs." if terrain_m >= 250 else ""
        return (
            f"{condition}: {wind_knots} kt {direction} flow. Expect choppy seas in the "
            f"Menorca and Ibiza channels.{terrain_note}"
        )
    if condition == "Moderate Wind":
        return f"Moderate wind from {direction} at {wind_knots} kt. Conditions are usable but monitor exposed crossings."
    return f"Favorable: {wind_knots} kt {direction} flow. Conditions look manageable for normal yacht operations."


def _route_assessment(worst: dict[str, Any], sample_count: int) -> str:
    location = worst["location"]["nearest_grid"]
    return (
        f"Worst sampled point across {sample_count} route checks is near "
        f"{location['lat']:.4f}, {location['lon']:.4f}: {worst['risk_assessment']}"
    )


def _wind_speed_grid(dataset: xr.Dataset, time_index: int) -> np.ndarray:
    _require_variables(dataset, ["U10", "V10"])
    u = _time_slice(dataset["U10"], time_index).values
    v = _time_slice(dataset["V10"], time_index).values
    return np.sqrt(u**2 + v**2) * MPS_TO_KNOTS


def _dijkstra_grid_path(
    wind_knots: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
) -> tuple[list[tuple[int, int]], float]:
    rows, cols = wind_knots.shape
    frontier = [(0.0, start)]
    distances = {start: 0.0}
    previous: dict[tuple[int, int], tuple[int, int]] = {}

    while frontier:
        current_cost, current = heapq.heappop(frontier)
        if current == end:
            return _reconstruct_path(previous, start, end), current_cost
        if current_cost > distances[current]:
            continue

        for neighbor in _grid_neighbors(current, rows, cols):
            step_distance = _grid_cell_distance_km(lats, lons, current, neighbor)
            edge_cost = step_distance * (1.0 + float(wind_knots[neighbor]) / 30.0)
            new_cost = current_cost + edge_cost
            if new_cost < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_cost
                previous[neighbor] = current
                heapq.heappush(frontier, (new_cost, neighbor))

    raise MarinerInterpreterError("No route found across WRF grid.")


def _grid_neighbors(
    cell: tuple[int, int],
    rows: int,
    cols: int,
) -> list[tuple[int, int]]:
    grid_j, grid_i = cell
    neighbors = []
    for delta_j in (-1, 0, 1):
        for delta_i in (-1, 0, 1):
            if delta_j == 0 and delta_i == 0:
                continue
            next_j = grid_j + delta_j
            next_i = grid_i + delta_i
            if 0 <= next_j < rows and 0 <= next_i < cols:
                neighbors.append((next_j, next_i))
    return neighbors


def _reconstruct_path(
    previous: dict[tuple[int, int], tuple[int, int]],
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[tuple[int, int]]:
    path = [end]
    current = end
    while current != start:
        current = previous[current]
        path.append(current)
    path.reverse()
    return path


def _route_point_from_grid(
    dataset: xr.Dataset,
    grid_j: int,
    grid_i: int,
    time_index: int,
    wind_knots_grid: np.ndarray,
) -> dict[str, Any]:
    values = _extract_point_values(dataset, grid_j, grid_i, time_index)
    wind_knots = int(round(float(wind_knots_grid[grid_j, grid_i])))
    gust_factor = round(_gust_factor(wind_knots, values["terrain_m"]), 2)
    condition = _condition(wind_knots, gust_factor)
    lats = _time_slice(dataset["XLAT"], time_index)
    lons = _time_slice(dataset["XLONG"], time_index)
    return {
        "lat": float(lats.values[grid_j, grid_i]),
        "lon": float(lons.values[grid_j, grid_i]),
        "grid_i": int(grid_i),
        "grid_j": int(grid_j),
        "wind_knots": wind_knots,
        "direction": wind_direction_cardinal(values["u10"], values["v10"]),
        "gust_factor": gust_factor,
        "condition": condition,
    }


def _path_distance_km(points: list[dict[str, Any]]) -> float:
    return sum(
        _haversine_km(
            points[index]["lat"],
            points[index]["lon"],
            points[index + 1]["lat"],
            points[index + 1]["lon"],
        )
        for index in range(len(points) - 1)
    )


def _grid_cell_distance_km(
    lats: np.ndarray,
    lons: np.ndarray,
    current: tuple[int, int],
    neighbor: tuple[int, int],
) -> float:
    current_j, current_i = current
    neighbor_j, neighbor_i = neighbor
    return _haversine_km(
        float(lats[current_j, current_i]),
        float(lons[current_j, current_i]),
        float(lats[neighbor_j, neighbor_i]),
        float(lons[neighbor_j, neighbor_i]),
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    a = sin(delta_lat / 2.0) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * asin(sqrt(a))


def _domain_label(path: Path) -> str:
    name = path.name
    for label in ("d01", "d02", "d03"):
        if label in name:
            return label
    return path.stem
