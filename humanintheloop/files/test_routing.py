"""
test_routing.py — PredSea Routing Unit Tests

These tests run without real NetCDF files by constructing
a synthetic 20x20 sea grid with known properties.

Run with: pytest test_routing.py -v
"""

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from route_graph import MaritimeGrid, GridPoint, WAVE_LIMITS
from route_solver import RouteSolver, RouteResult


# ---------------------------------------------------------------------------
# Synthetic grid fixture
# ---------------------------------------------------------------------------

def make_synthetic_grid(
    nrows: int = 20,
    ncols: int = 20,
    wave_hs_value: float = 0.5,
    current_u_value: float = 0.1,  # eastward m/s
    current_v_value: float = 0.0,
) -> MaritimeGrid:
    """
    Build a fully open (all-sea) rectangular grid centred near Mallorca.
    Lat: 38.5 to 40.5, Lon: 1.0 to 4.0
    """
    lats_1d = np.linspace(38.5, 40.5, nrows)
    lons_1d = np.linspace(1.0,  4.0,  ncols)
    lons_2d, lats_2d = np.meshgrid(lons_1d, lats_1d)

    sea_mask  = np.ones((nrows, ncols), dtype=bool)
    wave_hs   = np.full((nrows, ncols), wave_hs_value)
    current_u = np.full((nrows, ncols), current_u_value)
    current_v = np.full((nrows, ncols), current_v_value)

    grid = MaritimeGrid(
        lats=lats_2d,
        lons=lons_2d,
        sea_mask=sea_mask,
        wave_hs=wave_hs,
        current_u=current_u,
        current_v=current_v,
    )
    grid.build_vertex_index()
    return grid


def _write_simple_netcdf(path, wave_shape=(2, 2), current_shape=(2, 2)):
    from netCDF4 import Dataset

    with Dataset(path, "w") as ds:
        ds.createDimension("time", 2)
        ds.createDimension("latitude", wave_shape[0])
        ds.createDimension("longitude", wave_shape[1])
        time = ds.createVariable("time", "f8", ("time",))
        latitude = ds.createVariable("latitude", "f4", ("latitude",))
        longitude = ds.createVariable("longitude", "f4", ("longitude",))
        vhm0 = ds.createVariable("VHM0", "f4", ("time", "latitude", "longitude"))
        uo = ds.createVariable("uo", "f4", ("time", "latitude", "longitude"))
        vo = ds.createVariable("vo", "f4", ("time", "latitude", "longitude"))

        time[:] = [0, 1]
        latitude[:] = [39.0, 39.1]
        longitude[:] = [2.0, 2.1]
        vhm0[:] = [[[0.2, 0.3], [0.4, 0.5]], [[0.6, 0.7], [0.8, 0.9]]]
        uo[:] = [[[0.1, 0.2], [0.3, 0.4]], [[0.5, 0.6], [0.7, 0.8]]]
        vo[:] = [[[0.0, 0.1], [0.2, 0.3]], [[0.4, 0.5], [0.6, 0.7]]]


# ---------------------------------------------------------------------------
# route_graph tests
# ---------------------------------------------------------------------------

class TestMaritimeGrid:

    def test_vertex_count_all_sea(self):
        grid = make_synthetic_grid(10, 10)
        assert len(grid.sea_points) == 100

    def test_vertex_map_shape(self):
        grid = make_synthetic_grid(10, 10)
        assert grid.vertex_map.shape == (10, 10)

    def test_all_sea_points_have_valid_vertex_id(self):
        grid = make_synthetic_grid(10, 10)
        assert (grid.vertex_map >= 0).all()

    def test_land_mask_excludes_points(self):
        grid = make_synthetic_grid(10, 10)
        # Manually mask a point as land
        grid.sea_mask[5, 5] = False
        grid.build_vertex_index()
        assert len(grid.sea_points) == 99
        assert grid.vertex_map[5, 5] == -1

    def test_build_graph_time_priority(self):
        grid = make_synthetic_grid(10, 10)
        grid.build_graph(priority="time")
        assert grid.graph is not None
        assert grid.graph.shape == (100, 100)
        # Each interior point has 8 neighbours
        # Corner/edge points have fewer — just check non-empty
        assert grid.graph.nnz > 0

    def test_build_graph_comfort_priority(self):
        grid = make_synthetic_grid(10, 10)
        grid.build_graph(priority="comfort")
        assert grid.priority == "comfort"
        assert grid.graph is not None

    def test_build_graph_safety_excludes_high_wave_edges(self):
        # Set wave height above medium vessel limit everywhere
        limit = WAVE_LIMITS["medium"]
        grid = make_synthetic_grid(10, 10, wave_hs_value=limit + 0.5)
        grid.build_graph(priority="safety", vessel_class="medium")
        # All edges should be excluded — graph should be empty
        assert grid.graph.nnz == 0

    def test_build_graph_safety_keeps_calm_edges(self):
        grid = make_synthetic_grid(10, 10, wave_hs_value=0.3)
        grid.build_graph(priority="safety", vessel_class="medium")
        assert grid.graph.nnz > 0

    def test_haversine_is_positive(self):
        grid = make_synthetic_grid(10, 10)
        d = grid._haversine_nm(0, 0, 0, 1)
        assert d > 0

    def test_haversine_diagonal_larger_than_axis(self):
        grid = make_synthetic_grid(10, 10)
        d_axis = grid._haversine_nm(0, 0, 0, 1)
        d_diag = grid._haversine_nm(0, 0, 1, 1)
        assert d_diag > d_axis

    def test_effective_speed_with_tailwind_current(self):
        """Eastward current should increase effective speed going east."""
        grid = make_synthetic_grid(10, 10, current_u_value=1.0)  # 1.944 kn east
        # r=5, c=5 -> r=5, c=6 is eastward
        speed_base = 10.0
        eff = grid._effective_speed(5, 5, 5, 6, speed_base)
        assert eff > speed_base

    def test_effective_speed_with_headwind_current(self):
        """Eastward current should reduce effective speed going west."""
        grid = make_synthetic_grid(10, 10, current_u_value=1.0)
        speed_base = 10.0
        eff = grid._effective_speed(5, 6, 5, 5, speed_base)  # going west
        assert eff < speed_base

    def test_save_and_load(self, tmp_path):
        grid = make_synthetic_grid(10, 10)
        grid.build_graph(priority="time")
        save_path = str(tmp_path / "test_grid.pkl")
        grid.save(save_path)
        loaded = MaritimeGrid.load(save_path)
        assert loaded.graph is not None
        assert loaded.graph.shape == grid.graph.shape

    def test_from_netcdf_accepts_three_dimensional_currents(self, tmp_path):
        waves_path = tmp_path / "waves.nc"
        currents_path = tmp_path / "currents.nc"
        _write_simple_netcdf(waves_path)
        _write_simple_netcdf(currents_path)

        grid = MaritimeGrid.from_netcdf(str(waves_path), str(currents_path), lat_bounds=(38.5, 39.5), lon_bounds=(1.5, 2.5))
        assert grid.current_u.shape == grid.wave_hs.shape
        assert grid.current_v.shape == grid.wave_hs.shape


# ---------------------------------------------------------------------------
# route_solver tests
# ---------------------------------------------------------------------------

class TestRouteSolver:

    def _make_solver(self, priority="time", **kwargs) -> RouteSolver:
        grid = make_synthetic_grid(**kwargs)
        grid.build_graph(priority=priority)
        return RouteSolver(grid)

    def test_solve_returns_result(self):
        solver = self._make_solver()
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
            origin_place_id="test_origin",
            destination_place_id="test_dest",
        )
        assert result is not None
        assert isinstance(result, RouteResult)

    def test_solve_distance_positive(self):
        solver = self._make_solver()
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
        )
        assert result.distance_nm > 0

    def test_solve_estimated_time_positive(self):
        solver = self._make_solver()
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
        )
        assert result.estimated_time_h > 0

    def test_solve_waypoints_non_empty(self):
        solver = self._make_solver()
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
        )
        assert len(result.waypoints) > 0

    def test_solve_waypoints_start_near_origin(self):
        solver = self._make_solver()
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
        )
        first = result.waypoints[0]
        assert abs(first.lat - 38.6) < 0.2
        assert abs(first.lon - 1.2) < 0.3

    def test_solve_waypoints_end_near_destination(self):
        solver = self._make_solver()
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
        )
        last = result.waypoints[-1]
        assert abs(last.lat - 40.4) < 0.2
        assert abs(last.lon - 3.8) < 0.3

    def test_solve_to_api_response_shape(self):
        solver = self._make_solver()
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
            origin_place_id="palma",
            destination_place_id="menorca",
        )
        api = result.to_api_response()
        assert "distance_nm" in api
        assert "estimated_time_h" in api
        assert "waypoints" in api
        assert isinstance(api["waypoints"], list)

    def test_solve_place_ids_preserved(self):
        solver = self._make_solver()
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
            origin_place_id="palma",
            destination_place_id="menorca",
        )
        assert result.origin_place_id == "palma"
        assert result.destination_place_id == "menorca"

    def test_solve_with_favourable_current_faster(self):
        """Route going east should be faster with eastward current."""
        solver_no_curr  = self._make_solver(current_u_value=0.0)
        solver_with_curr = self._make_solver(current_u_value=1.0)

        kw = dict(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=38.6, destination_lon=3.5,  # pure east
        )
        r_no   = solver_no_curr.solve(**kw)
        r_with = solver_with_curr.solve(**kw)

        assert r_no is not None and r_with is not None
        assert r_with.estimated_time_h < r_no.estimated_time_h

    def test_snap_out_of_range_returns_none(self):
        solver = self._make_solver()
        # Point far outside the grid
        result = solver.solve(
            origin_lat=0.0, origin_lon=0.0,
            destination_lat=40.4, destination_lon=3.8,
        )
        assert result is None

    def test_no_path_on_empty_graph(self):
        """When safety mode excludes all edges, solve returns None."""
        limit = WAVE_LIMITS["medium"]
        grid = make_synthetic_grid(10, 10, wave_hs_value=limit + 1.0)
        grid.build_graph(priority="safety", vessel_class="medium")
        solver = RouteSolver(grid)
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=40.4, destination_lon=3.8,
        )
        assert result is None

    def test_decimate_path_max_points(self):
        solver = self._make_solver()
        long_path = list(range(200))
        decimated = solver._decimate_path(long_path, max_points=50)
        assert len(decimated) <= 50
        assert decimated[0] == 0
        assert decimated[-1] == 199

    def test_decimate_path_short_unchanged(self):
        solver = self._make_solver()
        short_path = list(range(10))
        decimated = solver._decimate_path(short_path, max_points=50)
        assert decimated == short_path


# ---------------------------------------------------------------------------
# Integration smoke test (canonical Balearic pair on synthetic grid)
# ---------------------------------------------------------------------------

class TestCanonicalRoutes:

    def test_palma_to_ibiza_synthetic(self):
        """
        Smoke test: solve Palma->Ibiza on a synthetic all-sea grid.
        The grid doesn't match real geography but confirms the pipeline runs end to end.
        """
        grid = make_synthetic_grid(
            nrows=30, ncols=30,
            wave_hs_value=0.8,
            current_u_value=0.05,
        )
        grid.build_graph(priority="comfort", vessel_class="medium")
        solver = RouteSolver(grid)

        # Use approximate coords within the synthetic grid bounds
        result = solver.solve(
            origin_lat=38.6, origin_lon=1.2,
            destination_lat=39.8, destination_lon=3.5,
            origin_place_id="palma",
            destination_place_id="ibiza_proxy",
            vessel_speed_kn=10.0,
        )

        assert result is not None
        assert result.distance_nm > 0
        assert result.estimated_time_h > 0
        assert result.avg_wave_hs_m == pytest.approx(0.8, abs=0.1)
        assert len(result.waypoints) > 2
