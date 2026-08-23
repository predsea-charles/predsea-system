"""
route_graph.py — PredSea Maritime Routing Graph Builder

Builds a sparse weighted graph from Copernicus NetCDF grids.
One vertex per sea grid point, edges to 8 neighbours.
Edge weights depend on optimisation mode: time, comfort, or safety.

Usage:
    grid = MaritimeGrid.from_netcdf(waves_path, currents_path)
    grid.build_graph(priority="comfort")
    grid.save("cache/grid_2026-06-14.pkl")
"""

import numpy as np
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import logging

try:
    import netCDF4 as nc
except ImportError:
    nc = None  # allow import without netCDF4 for unit tests

from scipy.sparse import csr_matrix

logger = logging.getLogger(__name__)

WAVE_HEIGHT_VARIABLE = "VHM0"
CURRENT_U_VARIABLE = "uo"
CURRENT_V_VARIABLE = "vo"


def _latest_current_slice(variable):
    logger.info("%s: dimensions=%s shape=%s", getattr(variable, "name", "current"), variable.dimensions, variable.shape)
    if variable.ndim == 4:
        return variable[-1, 0, :, :]
    if variable.ndim == 3:
        return variable[-1, :, :]
    if variable.ndim == 2:
        return variable[:, :]
    raise ValueError(
        f"Unsupported current variable shape {variable.shape} for {getattr(variable, 'name', 'unknown')}"
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 8-connectivity offsets: (row_delta, col_delta)
NEIGHBOUR_OFFSETS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0,  -1),           (0,  1),
    (1,  -1),  (1, 0),  (1,  1),
]

# Diagonal distance factor (sqrt(2) for diagonal neighbours)
DIAG_FACTOR = np.sqrt(2)

# Vessel class wave thresholds (metres) — hard exclude above this
WAVE_LIMITS = {
    "small":  1.0,   # <10m vessel
    "medium": 2.0,   # 10-20m
    "large":  3.5,   # 20m+
}

# Comfort penalty coefficient — tune with Graham's feedback
# edge_weight = travel_time * (1 + ALPHA * wave_height_m)
COMFORT_ALPHA = 0.4


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GridPoint:
    """A single sea grid point."""
    row: int
    col: int
    lat: float
    lon: float
    vertex_id: int  # flat index into the sea-point array


@dataclass
class MaritimeGrid:
    """
    The full Copernicus grid masked to sea points only.

    Attributes
    ----------
    lats, lons : 2D arrays of shape (nrows, ncols)
    sea_mask   : 2D bool array, True where navigable
    wave_hs    : 2D significant wave height (m)
    current_u  : 2D eastward current (m/s)
    current_v  : 2D northward current (m/s)
    vertex_map : 2D int array mapping (row, col) -> vertex_id, -1 for land
    sea_points : list of GridPoint in vertex_id order
    graph      : scipy csr_matrix (built by build_graph)
    priority   : str used when graph was built
    """
    lats: np.ndarray
    lons: np.ndarray
    sea_mask: np.ndarray
    wave_hs: np.ndarray
    current_u: np.ndarray
    current_v: np.ndarray
    vertex_map: np.ndarray = field(default_factory=lambda: np.array([]))
    sea_points: list = field(default_factory=list)
    graph: Optional[csr_matrix] = None
    priority: str = "time"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_netcdf(
        cls,
        waves_path: str,
        currents_path: str,
        lat_bounds: tuple = (35.0, 44.5),
        lon_bounds: tuple = (-5.0, 10.0),
    ) -> "MaritimeGrid":
        """
        Load Copernicus Mediterranean wave and current NetCDF files
        and crop to the Balearic / western Med domain.

        Expected variables:
          waves:    VHM0 (sig wave height), VMDR (mean wave direction)
          currents: uo (eastward), vo (northward)
          both:     latitude, longitude, time

        These variable names match the Copernicus ETL output used by PredSea.
        """
        if nc is None:
            raise ImportError("netCDF4 is required: pip install netCDF4")

        logger.info("Loading waves from %s", waves_path)
        with nc.Dataset(waves_path) as ds:
            raw_lats = ds.variables["latitude"][:]
            raw_lons = ds.variables["longitude"][:]
            # Take the latest available timestep
            wave_hs_raw = ds.variables[WAVE_HEIGHT_VARIABLE][-1, :, :]

        logger.info("Loading currents from %s", currents_path)
        with nc.Dataset(currents_path) as ds:
            curr_u_raw = _latest_current_slice(ds.variables[CURRENT_U_VARIABLE])
            curr_v_raw = _latest_current_slice(ds.variables[CURRENT_V_VARIABLE])

        # Crop to domain
        lat_idx = np.where(
            (raw_lats >= lat_bounds[0]) & (raw_lats <= lat_bounds[1])
        )[0]
        lon_idx = np.where(
            (raw_lons >= lon_bounds[0]) & (raw_lons <= lon_bounds[1])
        )[0]

        lats_1d = raw_lats[lat_idx]
        lons_1d = raw_lons[lon_idx]
        lons_2d, lats_2d = np.meshgrid(lons_1d, lats_1d)

        wave_hs = wave_hs_raw[np.ix_(lat_idx, lon_idx)]
        curr_u  = curr_u_raw[np.ix_(lat_idx, lon_idx)]
        curr_v  = curr_v_raw[np.ix_(lat_idx, lon_idx)]

        # Sea mask: where wave data is valid (not masked / fill value)
        if hasattr(wave_hs, "mask"):
            sea_mask = ~wave_hs.mask
            wave_hs  = np.where(sea_mask, wave_hs.data, 0.0)
            curr_u   = np.where(sea_mask, curr_u.data if hasattr(curr_u, "data") else curr_u, 0.0)
            curr_v   = np.where(sea_mask, curr_v.data if hasattr(curr_v, "data") else curr_v, 0.0)
        else:
            # fallback: treat very large fill values as land
            fill = 9.96921e+36
            sea_mask = (wave_hs < fill * 0.9)
            wave_hs  = np.where(sea_mask, wave_hs, 0.0)

        logger.info(
            "Grid: %d x %d, %d sea points (%.1f%% sea)",
            lats_2d.shape[0], lats_2d.shape[1],
            sea_mask.sum(),
            100 * sea_mask.sum() / sea_mask.size,
        )

        return cls(
            lats=lats_2d,
            lons=lons_2d,
            sea_mask=sea_mask,
            wave_hs=wave_hs,
            current_u=curr_u,
            current_v=curr_v,
        )

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------

    def build_vertex_index(self) -> None:
        """
        Assign a vertex_id to every sea point and build sea_points list.
        Land points get vertex_id = -1.
        """
        nrows, ncols = self.sea_mask.shape
        self.vertex_map = np.full((nrows, ncols), -1, dtype=np.int32)
        self.sea_points = []

        vid = 0
        for r in range(nrows):
            for c in range(ncols):
                if self.sea_mask[r, c]:
                    self.vertex_map[r, c] = vid
                    self.sea_points.append(GridPoint(
                        row=r, col=c,
                        lat=float(self.lats[r, c]),
                        lon=float(self.lons[r, c]),
                        vertex_id=vid,
                    ))
                    vid += 1

        logger.info("Vertex index built: %d vertices", vid)

    # ------------------------------------------------------------------
    # Distance helpers
    # ------------------------------------------------------------------

    def _haversine_nm(self, r1, c1, r2, c2) -> float:
        """Great-circle distance in nautical miles between two grid points."""
        lat1, lon1 = np.radians(self.lats[r1, c1]), np.radians(self.lons[r1, c1])
        lat2, lon2 = np.radians(self.lats[r2, c2]), np.radians(self.lons[r2, c2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        return c * 3440.065  # Earth radius in nautical miles

    def _effective_speed(self, r1, c1, r2, c2, vessel_speed_kn: float) -> float:
        """
        Vessel speed adjusted for current component along the edge direction.
        Returns effective speed in knots (minimum 0.5 kn to avoid division issues).
        """
        # Edge bearing vector (simplified flat approximation — fine at this scale)
        dy = self.lats[r2, c2] - self.lats[r1, c1]
        dx = self.lons[r2, c2] - self.lons[r1, c1]
        norm = np.sqrt(dx**2 + dy**2)
        if norm == 0:
            return vessel_speed_kn

        ux, uy = dx / norm, dy / norm  # unit vector in lat/lon space

        # Current at midpoint (average of the two endpoints)
        cu = 0.5 * (self.current_u[r1, c1] + self.current_u[r2, c2])  # m/s east
        cv = 0.5 * (self.current_v[r1, c1] + self.current_v[r2, c2])  # m/s north

        # Project current onto edge direction (convert m/s -> knots: * 1.944)
        current_component_kn = (cu * ux + cv * uy) * 1.944

        effective = vessel_speed_kn + current_component_kn
        return max(effective, 0.5)

    # ------------------------------------------------------------------
    # Graph builder
    # ------------------------------------------------------------------

    def build_graph(
        self,
        priority: str = "comfort",
        vessel_class: str = "medium",
        vessel_speed_kn: float = 10.0,
    ) -> None:
        """
        Build the sparse weighted graph for all sea points.

        Parameters
        ----------
        priority      : "time" | "comfort" | "safety"
        vessel_class  : "small" | "medium" | "large"
        vessel_speed_kn : base vessel speed in knots
        """
        if not self.sea_points:
            self.build_vertex_index()

        wave_limit = WAVE_LIMITS[vessel_class]
        n = len(self.sea_points)
        nrows, ncols = self.sea_mask.shape

        rows_list, cols_list, data_list = [], [], []

        logger.info(
            "Building graph: %d vertices, priority=%s, vessel=%s",
            n, priority, vessel_class
        )

        for gp in self.sea_points:
            r, c = gp.row, gp.col
            vid = gp.vertex_id

            for dr, dc in NEIGHBOUR_OFFSETS:
                nr, nc_ = r + dr, c + dc

                # Bounds check
                if not (0 <= nr < nrows and 0 <= nc_ < ncols):
                    continue

                # Land check
                if not self.sea_mask[nr, nc_]:
                    continue

                nbr_vid = self.vertex_map[nr, nc_]
                if nbr_vid < 0:
                    continue

                # --- Wave safety hard limit ---
                wave_at_edge = max(self.wave_hs[r, c], self.wave_hs[nr, nc_])
                if priority == "safety" and wave_at_edge > wave_limit:
                    continue  # exclude this edge entirely

                # --- Distance ---
                dist_nm = self._haversine_nm(r, c, nr, nc_)

                # --- Edge weight ---
                eff_speed = self._effective_speed(r, c, nr, nc_, vessel_speed_kn)
                travel_time_h = dist_nm / eff_speed

                if priority == "time":
                    weight = travel_time_h

                elif priority == "comfort":
                    # Penalise high waves — heavier penalty near vessel limit
                    wave_ratio = wave_at_edge / wave_limit
                    penalty = 1.0 + COMFORT_ALPHA * wave_ratio
                    weight = travel_time_h * penalty

                elif priority == "safety":
                    # Already excluded edges above the hard limit.
                    # Within safe range, prefer calmer water.
                    wave_ratio = wave_at_edge / wave_limit
                    penalty = 1.0 + 2.0 * wave_ratio  # stronger penalty than comfort
                    weight = travel_time_h * penalty

                else:
                    raise ValueError(f"Unknown priority: {priority}")

                rows_list.append(vid)
                cols_list.append(nbr_vid)
                data_list.append(weight)

        self.graph = csr_matrix(
            (data_list, (rows_list, cols_list)),
            shape=(n, n),
        )
        self.priority = priority
        logger.info("Graph built: %d edges", len(data_list))

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("Grid saved to %s", path)

    @classmethod
    def load(cls, path: str) -> "MaritimeGrid":
        with open(path, "rb") as f:
            grid = pickle.load(f)
        logger.info("Grid loaded from %s", path)
        return grid
