"""
route_solver.py — PredSea Dijkstra Route Solver

Given a built MaritimeGrid, finds the optimal path between two
lat/lon coordinates using scipy's Dijkstra implementation.

Returns a RouteResult with waypoints, distance, estimated time,
and average conditions along the path.
"""

import numpy as np
import logging
from dataclasses import dataclass, field
from typing import Optional

from scipy.sparse.csgraph import dijkstra

from route_graph import MaritimeGrid, GridPoint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class Waypoint:
    lat: float
    lon: float
    wave_hs_m: float
    current_kn: float


@dataclass
class RouteResult:
    """
    The output of a single route solve.
    Stored in BigQuery / GCS and served by the API.
    """
    origin_place_id: str
    destination_place_id: str
    origin_lat: float
    origin_lon: float
    destination_lat: float
    destination_lon: float
    priority: str
    vessel_class: str
    vessel_speed_kn: float

    # Path summary
    distance_nm: float = 0.0
    estimated_time_h: float = 0.0
    waypoints: list = field(default_factory=list)  # list of Waypoint

    # Conditions along path
    avg_wave_hs_m: float = 0.0
    max_wave_hs_m: float = 0.0
    avg_current_kn: float = 0.0
    favourable_current_pct: float = 0.0  # % of edges with current assistance

    # Metadata
    forecast_run_utc: str = ""
    computed_at_utc: str = ""
    solver_version: str = "v1"

    # Routing grid snap info (for debugging)
    origin_vertex_id: int = -1
    destination_vertex_id: int = -1
    origin_snap_dist_nm: float = 0.0
    destination_snap_dist_nm: float = 0.0

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "waypoints"}
        d["waypoints"] = [w.__dict__ for w in self.waypoints]
        return d

    def to_api_response(self) -> dict:
        """Minimal response shape for the API layer."""
        return {
            "origin": self.origin_place_id,
            "destination": self.destination_place_id,
            "priority": self.priority,
            "vessel_class": self.vessel_class,
            "distance_nm": round(self.distance_nm, 1),
            "estimated_time_h": round(self.estimated_time_h, 2),
            "avg_wave_hs_m": round(self.avg_wave_hs_m, 2),
            "max_wave_hs_m": round(self.max_wave_hs_m, 2),
            "avg_current_kn": round(self.avg_current_kn, 2),
            "favourable_current_pct": round(self.favourable_current_pct, 1),
            "waypoints": [
                {"lat": round(w.lat, 4), "lon": round(w.lon, 4)}
                for w in self.waypoints
            ],
            "forecast_run_utc": self.forecast_run_utc,
            "computed_at_utc": self.computed_at_utc,
        }


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

class RouteSolver:
    """
    Wraps a MaritimeGrid and solves optimal routes between place pairs.
    """

    def __init__(self, grid: MaritimeGrid):
        self.grid = grid
        if self.grid.graph is None:
            raise ValueError("Grid graph not built. Call grid.build_graph() first.")

    # ------------------------------------------------------------------
    # Coordinate snapping
    # ------------------------------------------------------------------

    def _snap_to_sea(self, lat: float, lon: float) -> Optional[GridPoint]:
        """
        Find the nearest sea vertex to a given lat/lon.
        Returns None if no sea point found within 0.5 degrees.
        """
        best_gp = None
        best_dist = float("inf")

        for gp in self.grid.sea_points:
            d = (gp.lat - lat)**2 + (gp.lon - lon)**2
            if d < best_dist:
                best_dist = d
                best_gp = gp

        if best_dist > 0.5**2:  # ~30nm threshold
            logger.warning(
                "Could not snap (%.4f, %.4f) to a sea point — nearest at %.2f deg",
                lat, lon, best_dist**0.5
            )
            return None

        return best_gp

    def _haversine_nm(self, lat1, lon1, lat2, lon2) -> float:
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
        return 2 * np.arcsin(np.sqrt(a)) * 3440.065

    # ------------------------------------------------------------------
    # Path reconstruction
    # ------------------------------------------------------------------

    def _reconstruct_path(
        self,
        predecessors: np.ndarray,
        origin_vid: int,
        dest_vid: int,
    ) -> list[int]:
        """Walk predecessor array back from destination to origin."""
        path = []
        current = dest_vid
        while current != origin_vid:
            if current < 0 or predecessors[current] < 0:
                logger.error("No path found from %d to %d", origin_vid, dest_vid)
                return []
            path.append(current)
            current = predecessors[current]
        path.append(origin_vid)
        path.reverse()
        return path

    # ------------------------------------------------------------------
    # Path decimation (reduce waypoints for API response)
    # ------------------------------------------------------------------

    def _decimate_path(self, path_vids: list[int], max_points: int = 50) -> list[int]:
        """
        Reduce path to at most max_points waypoints using uniform sampling.
        Always keeps first and last point.
        """
        if len(path_vids) <= max_points:
            return path_vids
        indices = np.round(np.linspace(0, len(path_vids) - 1, max_points)).astype(int)
        return [path_vids[i] for i in indices]

    # ------------------------------------------------------------------
    # Core solve
    # ------------------------------------------------------------------

    def solve(
        self,
        origin_lat: float,
        origin_lon: float,
        destination_lat: float,
        destination_lon: float,
        origin_place_id: str = "origin",
        destination_place_id: str = "destination",
        vessel_speed_kn: float = 10.0,
        forecast_run_utc: str = "",
        computed_at_utc: str = "",
    ) -> Optional[RouteResult]:
        """
        Run Dijkstra from origin to destination and return a RouteResult.
        Returns None if no path exists.
        """
        # Snap to grid
        origin_gp = self._snap_to_sea(origin_lat, origin_lon)
        dest_gp   = self._snap_to_sea(destination_lat, destination_lon)

        if origin_gp is None or dest_gp is None:
            logger.error("Failed to snap one or both endpoints to sea grid.")
            return None

        origin_snap_dist = self._haversine_nm(
            origin_lat, origin_lon, origin_gp.lat, origin_gp.lon
        )
        dest_snap_dist = self._haversine_nm(
            destination_lat, destination_lon, dest_gp.lat, dest_gp.lon
        )

        logger.info(
            "Solving %s -> %s (vertex %d -> %d)",
            origin_place_id, destination_place_id,
            origin_gp.vertex_id, dest_gp.vertex_id,
        )

        # Run Dijkstra from origin only (directed=False for undirected passability,
        # but we use directed=True because currents make edges asymmetric)
        dist_array, predecessors = dijkstra(
            self.grid.graph,
            directed=True,
            indices=origin_gp.vertex_id,
            return_predecessors=True,
        )

        if dist_array[dest_gp.vertex_id] == np.inf:
            logger.error(
                "No navigable path found from %s to %s",
                origin_place_id, destination_place_id,
            )
            return None

        # Reconstruct full path
        path_vids = self._reconstruct_path(
            predecessors, origin_gp.vertex_id, dest_gp.vertex_id
        )

        if not path_vids:
            return None

        # Build waypoints and compute summary metrics
        waypoints_full = []
        total_dist_nm = 0.0
        wave_values = []
        current_components = []
        favourable_count = 0

        for i, vid in enumerate(path_vids):
            gp = self.grid.sea_points[vid]
            r, c = gp.row, gp.col

            curr_u = float(self.grid.current_u[r, c])
            curr_v = float(self.grid.current_v[r, c])
            current_speed_kn = np.sqrt(curr_u**2 + curr_v**2) * 1.944

            waypoints_full.append(Waypoint(
                lat=gp.lat,
                lon=gp.lon,
                wave_hs_m=float(self.grid.wave_hs[r, c]),
                current_kn=round(current_speed_kn, 2),
            ))
            wave_values.append(self.grid.wave_hs[r, c])

            # Edge stats (between consecutive points)
            if i > 0:
                prev_gp = self.grid.sea_points[path_vids[i - 1]]
                edge_dist = self._haversine_nm(
                    prev_gp.lat, prev_gp.lon, gp.lat, gp.lon
                )
                total_dist_nm += edge_dist

                # Current component along edge
                dy = gp.lat - prev_gp.lat
                dx = gp.lon - prev_gp.lon
                norm = np.sqrt(dx**2 + dy**2)
                if norm > 0:
                    ux, uy = dx / norm, dy / norm
                    cu = 0.5 * (
                        self.grid.current_u[prev_gp.row, prev_gp.col] +
                        self.grid.current_u[r, c]
                    )
                    cv = 0.5 * (
                        self.grid.current_v[prev_gp.row, prev_gp.col] +
                        self.grid.current_v[r, c]
                    )
                    proj = (cu * ux + cv * uy) * 1.944
                    current_components.append(proj)
                    if proj > 0:
                        favourable_count += 1

        # Estimated passage time
        avg_eff_speed = vessel_speed_kn + (
            np.mean(current_components) if current_components else 0.0
        )
        avg_eff_speed = max(avg_eff_speed, 0.5)
        estimated_time_h = total_dist_nm / avg_eff_speed

        favourable_pct = (
            100.0 * favourable_count / len(current_components)
            if current_components else 0.0
        )

        # Decimate for API response
        decimated_vids = self._decimate_path(path_vids, max_points=60)
        decimated_waypoints = [waypoints_full[path_vids.index(v)] for v in decimated_vids]

        return RouteResult(
            origin_place_id=origin_place_id,
            destination_place_id=destination_place_id,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
            priority=self.grid.priority,
            vessel_class="medium",  # passed through from grid build
            vessel_speed_kn=vessel_speed_kn,
            distance_nm=round(total_dist_nm, 1),
            estimated_time_h=round(estimated_time_h, 2),
            waypoints=decimated_waypoints,
            avg_wave_hs_m=round(float(np.mean(wave_values)), 2),
            max_wave_hs_m=round(float(np.max(wave_values)), 2),
            avg_current_kn=round(float(np.mean([abs(c) for c in current_components])), 2) if current_components else 0.0,
            favourable_current_pct=round(favourable_pct, 1),
            forecast_run_utc=forecast_run_utc,
            computed_at_utc=computed_at_utc,
            origin_vertex_id=origin_gp.vertex_id,
            destination_vertex_id=dest_gp.vertex_id,
            origin_snap_dist_nm=round(origin_snap_dist, 2),
            destination_snap_dist_nm=round(dest_snap_dist, 2),
        )
