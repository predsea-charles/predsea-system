from pathlib import Path

from processing.mariner_interpreter import (
    compare_optimal_routes,
    get_captain_summary,
    get_optimal_route,
    get_route_summary,
    nearest_grid_point,
    sample_route_points,
    wind_direction_cardinal,
)


FIXTURE = Path("processing/fixtures/wrfout_d03_sample.nc")
D01_FIXTURE = Path("processing/fixtures/wrfout_d01_sample.nc")
D02_FIXTURE = Path("processing/fixtures/wrfout_d02_sample.nc")


def test_nearest_grid_point_finds_fixture_location():
    point = nearest_grid_point(FIXTURE, lat=39.5, lon=3.2)

    assert point["grid_i"] >= 0
    assert point["grid_j"] >= 0
    assert abs(point["lat"] - 39.5) < 0.05
    assert abs(point["lon"] - 3.2) < 0.05


def test_wind_direction_cardinal_uses_meteorological_direction():
    assert wind_direction_cardinal(u=0.0, v=-5.0) == "N"
    assert wind_direction_cardinal(u=-5.0, v=0.0) == "E"
    assert wind_direction_cardinal(u=5.0, v=0.0) == "W"


def test_get_captain_summary_returns_llm_ready_json_from_wrfout():
    summary = get_captain_summary(lat=39.5, lon=3.2, time=None, wrfout_path=FIXTURE)

    assert set(summary) == {
        "condition",
        "wind_knots",
        "direction",
        "gust_factor",
        "sea_state_stability",
        "risk_assessment",
        "source",
        "location",
        "metrics",
    }
    assert isinstance(summary["wind_knots"], int)
    assert summary["wind_knots"] >= 0
    assert summary["direction"] in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
    assert summary["gust_factor"] >= 1.0
    assert "wrfout_d03_sample.nc" in summary["source"]
    assert "nearest_grid" in summary["location"]
    assert "temperature_c" in summary["metrics"]
    assert "pressure_hpa" in summary["metrics"]
    assert isinstance(summary["risk_assessment"], str)
    assert summary["risk_assessment"]


def test_sample_route_points_includes_start_end_and_midpoints():
    points = sample_route_points(
        start_lat=39.3,
        start_lon=3.0,
        end_lat=39.8,
        end_lon=3.6,
        samples=4,
    )

    assert points == [
        {"lat": 39.3, "lon": 3.0},
        {"lat": 39.466667, "lon": 3.2},
        {"lat": 39.633333, "lon": 3.4},
        {"lat": 39.8, "lon": 3.6},
    ]


def test_get_route_summary_returns_worst_point_and_route_guidance():
    summary = get_route_summary(
        start_lat=39.3,
        start_lon=3.0,
        end_lat=39.8,
        end_lon=3.6,
        time=None,
        wrfout_path=FIXTURE,
        samples=4,
    )

    assert set(summary) == {
        "condition",
        "route_summary",
        "worst_point",
        "samples",
        "sample_count",
        "source",
    }
    assert summary["sample_count"] == 4
    assert len(summary["samples"]) == 4
    assert summary["worst_point"] in summary["samples"]
    assert summary["condition"] == summary["worst_point"]["condition"]
    assert "Worst sampled point" in summary["route_summary"]


def test_get_optimal_route_returns_dijkstra_path_for_wind_cost():
    route = get_optimal_route(
        start_lat=39.3,
        start_lon=3.0,
        end_lat=39.8,
        end_lon=3.6,
        time=None,
        wrfout_path=FIXTURE,
        cost_field="wind",
    )

    assert route["route_type"] == "lowest_wind"
    assert route["cost_field"] == "wind"
    assert route["total_cost"] > 0
    assert route["route_distance_km"] > 0
    assert len(route["points"]) >= 2
    assert route["points"][0]["lat"] == route["start"]["nearest_grid"]["lat"]
    assert route["points"][-1]["lat"] == route["end"]["nearest_grid"]["lat"]
    assert route["worst_point"] in route["points"]
    assert "lowest-wind" in route["summary"]


def test_get_optimal_route_rejects_unknown_cost_field():
    try:
        get_optimal_route(39.3, 3.0, 39.8, 3.6, None, FIXTURE, cost_field="temperature")
    except Exception as exc:
        assert "Unsupported cost_field" in str(exc)
    else:
        raise AssertionError("Expected unknown cost field to fail")


def test_compare_optimal_routes_returns_distance_by_domain():
    comparison = compare_optimal_routes(
        start_lat=39.3,
        start_lon=3.0,
        end_lat=39.8,
        end_lon=3.6,
        time=None,
        wrfout_paths=[D01_FIXTURE, D02_FIXTURE, FIXTURE],
        cost_field="wind",
    )

    assert comparison["route_count"] == 3
    assert [route["domain"] for route in comparison["routes"]] == ["d01", "d02", "d03"]
    assert all(route["route_distance_km"] > 0 for route in comparison["routes"])
    assert all(route["point_count"] >= 2 for route in comparison["routes"])
    assert "shortest_route" in comparison
    assert "longest_route" in comparison
    assert "distance_spread_km" in comparison
