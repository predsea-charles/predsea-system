import importlib.util
from pathlib import Path

import numpy as np
import xarray as xr


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_ocean_conditions_map.py"


def load_map_script():
    spec = importlib.util.spec_from_file_location("generate_ocean_conditions_map", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_select_time_index_accepts_hour_or_iso_fragment():
    module = load_map_script()
    dataset = xr.Dataset(coords={"time": np.array(["2026-05-15T06:00:00", "2026-05-15T12:00:00"], dtype="datetime64[ns]")})

    assert module.select_time_index(dataset, "12:00") == 1
    assert module.select_time_index(dataset, "2026-05-15T06:00") == 0
    assert module.select_time_index(dataset, "18:00") == 0


def test_infer_extent_uses_wave_grid_with_padding():
    module = load_map_script()
    wave = xr.DataArray(
        np.zeros((2, 3)),
        coords={"latitude": [39.0, 40.0], "longitude": [1.0, 2.0, 3.0]},
        dims=("latitude", "longitude"),
    )

    assert module.infer_extent(wave, padding_degrees=0.1) == [0.9, 3.1, 38.9, 40.1]


def test_quiver_steps_are_thinned_for_readable_map():
    module = load_map_script()

    assert module.quiver_steps(85, 48, "normal") == (6, 4)
    assert module.quiver_steps(85, 48, "sparse") == (8, 6)
    assert module.quiver_steps(85, 48, "dense") == (3, 3)


def test_cli_defaults_to_black_current_arrows():
    module = load_map_script()

    assert module.parse_args(["--waves", "waves.nc", "--output", "map.png"]).arrow_color == "black"


def test_cli_accepts_scalar_and_vector_variables():
    module = load_map_script()
    args = module.parse_args([
        "--waves", "waves.nc",
        "--output", "map.png",
        "--scalar-var", "VHM0_SW1",
        "--vector-var", "wave_dir",
        "--wind", "wind.nc",
    ])
    assert args.scalar_var == "VHM0_SW1"
    assert args.vector_var == "wave_dir"
    assert args.wind == "wind.nc"


SAMPLE_ROUTE = {
    "origin": {"name": "Palma", "latitude": 39.5696, "longitude": 2.6502},
    "destination": {"name": "Ibiza", "latitude": 38.9089, "longitude": 1.435},
    "sample_points": [
        {"name": "Mid Palma-Ibiza", "latitude": 39.19, "longitude": 2.04},
    ],
}


class FakeAStarWeatherRouter:
    """Stands in for api.weather_routing.AStarWeatherRouter so tests don't need real
    NetCDF grids. Tracks constructor/clear_cache calls so tests can assert on them."""

    init_calls = []
    clear_cache_calls = 0

    def __init__(self, waves_path=None, currents_path=None):
        FakeAStarWeatherRouter.init_calls.append((waves_path, currents_path))
        self.waves_path = waves_path
        self.currents_path = currents_path

    @classmethod
    def clear_cache(cls):
        cls.clear_cache_calls += 1

    def in_bounds(self, lat, lon):
        return True

    def find_route(self, origin_lat, origin_lon, dest_lat, dest_lon, departure_dt=None):
        return {
            "waypoints": [
                {"lat": origin_lat, "lng": origin_lon},
                {"lat": (origin_lat + dest_lat) / 2, "lng": (origin_lon + dest_lon) / 2},
                {"lat": dest_lat, "lng": dest_lon},
            ],
            "distance_nm": 42.0,
            "estimated_time_h": 2.8,
            "source_tag": "astar_weather_route_v1",
        }


class OutOfBoundsAStarWeatherRouter(FakeAStarWeatherRouter):
    def in_bounds(self, lat, lon):
        return False


def test_resolve_route_waypoints_prefers_waypoints_already_on_route():
    module = load_map_script()
    route = dict(SAMPLE_ROUTE, waypoints=[{"lat": 1.0, "lng": 2.0}])

    waypoints = module.resolve_route_waypoints(route, waves_path="waves.nc", currents_path="currents.nc")

    assert waypoints == [{"lat": 1.0, "lng": 2.0}]


def test_resolve_route_waypoints_uses_weather_router_with_forcing_files():
    module = load_map_script()
    FakeAStarWeatherRouter.init_calls = []
    FakeAStarWeatherRouter.clear_cache_calls = 0

    waypoints = module.waypoints_from_weather_router(
        SAMPLE_ROUTE, "waves.nc", "currents.nc", router_cls=FakeAStarWeatherRouter
    )

    assert FakeAStarWeatherRouter.clear_cache_calls == 1
    assert FakeAStarWeatherRouter.init_calls == [("waves.nc", "currents.nc")]
    assert waypoints[0] == {"lat": 39.5696, "lng": 2.6502}
    assert waypoints[-1] == {"lat": 38.9089, "lng": 1.435}
    assert len(waypoints) == 3


def test_waypoints_from_weather_router_returns_empty_without_currents_path():
    module = load_map_script()

    waypoints = module.waypoints_from_weather_router(
        SAMPLE_ROUTE, "waves.nc", None, router_cls=FakeAStarWeatherRouter
    )

    assert waypoints == []


def test_waypoints_from_weather_router_falls_back_when_out_of_bounds():
    module = load_map_script()

    waypoints = module.waypoints_from_weather_router(
        SAMPLE_ROUTE, "waves.nc", "currents.nc", router_cls=OutOfBoundsAStarWeatherRouter
    )

    assert waypoints == []


def test_waypoints_from_weather_router_swallows_routing_errors():
    module = load_map_script()

    class ExplodingRouter(FakeAStarWeatherRouter):
        def find_route(self, *args, **kwargs):
            raise RuntimeError("no navigable path found")

    waypoints = module.waypoints_from_weather_router(
        SAMPLE_ROUTE, "waves.nc", "currents.nc", router_cls=ExplodingRouter
    )

    assert waypoints == []


def test_waypoints_from_sample_points_prepends_origin_and_appends_destination():
    module = load_map_script()

    waypoints = module.waypoints_from_sample_points(SAMPLE_ROUTE)

    assert waypoints[0] == {"lat": 39.5696, "lng": 2.6502}
    assert waypoints[1] == {"lat": 39.19, "lng": 2.04}
    assert waypoints[-1] == {"lat": 38.9089, "lng": 1.435}


def test_resolve_route_waypoints_falls_back_to_sample_points_when_router_unavailable(monkeypatch):
    module = load_map_script()
    monkeypatch.setattr(module, "waypoints_from_place_registry", lambda route: [])
    # No waves/currents path given (as when called without forcing files) and place_registry
    # resolution isn't importable/available in this route dict -> should still get a route
    # from sample_points rather than an empty overlay.
    route = dict(SAMPLE_ROUTE)

    waypoints = module.resolve_route_waypoints(route, waves_path=None, currents_path=None)

    assert waypoints
    assert waypoints[0] == {"lat": 39.5696, "lng": 2.6502}
    assert waypoints[-1] == {"lat": 38.9089, "lng": 1.435}


def test_resolve_route_waypoints_passes_through_list_route():
    module = load_map_script()
    raw_waypoints = [{"lat": 1.0, "lng": 2.0}, {"lat": 3.0, "lng": 4.0}]

    assert module.resolve_route_waypoints(raw_waypoints) == raw_waypoints


def test_compute_map_extent_respects_explicit_override():
    module = load_map_script()
    override = [1.0, 5.0, 35.0, 45.0]
    assert module.compute_map_extent(None, extent=override) == override


def test_compute_map_extent_expands_to_encompass_waypoints():
    module = load_map_script()
    # Wave grid covers lat [39.0, 40.0], lon [1.0, 3.0]
    wave = xr.DataArray(
        np.zeros((2, 3)),
        coords={"latitude": [39.0, 40.0], "longitude": [1.0, 2.0, 3.0]},
        dims=("latitude", "longitude"),
    )
    # Default wave grid extent with 0.08 padding is [0.92, 3.08, 38.92, 40.08]
    # No waypoints -> returns default extent
    assert module.compute_map_extent(wave, waypoints=[]) == [0.92, 3.08, 38.92, 40.08]

    # Waypoints extending far to the north and east: Marseille and Cagliari alike (e.g. lat 43.3, lon 9.11)
    waypoints = [
        {"lat": 43.30, "lng": 5.37},
        {"lat": 39.21, "lng": 9.11},
    ]
    # Padded waypoints:
    # lon_min = 5.37 - 0.6 = 4.77
    # lon_max = 9.11 + 0.6 = 9.71
    # lat_min = 39.21 - 0.6 = 38.61
    # lat_max = 43.30 + 0.6 = 43.90
    #
    # Union of grid [0.92, 3.08, 38.92, 40.08] and padded waypoints:
    # lon_min: min(0.92, 4.77) = 0.92
    # lon_max: max(3.08, 9.71) = 9.71
    # lat_min: min(38.92, 38.61) = 38.61
    # lat_max: max(40.08, 43.90) = 43.90
    expected = [0.92, 9.71, 38.61, 43.90]
    result = module.compute_map_extent(wave, waypoints=waypoints)
    np.testing.assert_allclose(result, expected, atol=1e-5)


