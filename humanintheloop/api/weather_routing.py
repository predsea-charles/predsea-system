import os
import math
import heapq
import numpy as np
import xarray as xr
import pandas as pd

DEFAULT_VESSEL_SPEED_KN = 15.0
DEFAULT_W_WAVE = 0.5
DEFAULT_MAX_WAVE_HEIGHT = 2.5


class AStarWeatherRouter:
    _cached_waves = None
    _cached_currents = None

    def __init__(
        self,
        waves_path: str = None,
        currents_path: str = None,
        vessel_speed: float = DEFAULT_VESSEL_SPEED_KN,
        w_wave: float = DEFAULT_W_WAVE,
        max_wave_height: float = DEFAULT_MAX_WAVE_HEIGHT,
        vessel_profile = None,
    ):
        # Set paths to default if not provided
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if waves_path is None:
            waves_path = os.path.join(base_dir, "mvp_data", "balearic_waves.nc")
        if currents_path is None:
            currents_path = os.path.join(base_dir, "mvp_data", "balearic_currents.nc")

        self.waves_path = waves_path
        self.currents_path = currents_path
        self.w_wave = float(w_wave)

        if vessel_profile is not None:
            self.vessel_profile = vessel_profile
            self.vessel_speed = float(vessel_profile.cruising_speed_knots)
            self.max_wave_height = float(vessel_profile.max_wave_height_tolerance_m)
        else:
            from api.schemas import VesselProfile
            # Fallback to a default VesselProfile built from inputs
            self.vessel_profile = VesselProfile(
                cruising_speed_knots=float(vessel_speed),
                max_wave_height_tolerance_m=float(max_wave_height)
            )
            self.vessel_speed = float(vessel_speed)
            self.max_wave_height = float(max_wave_height)

        # Load datasets (using lazy-loaded class-level cache to optimize memory)
        self._load_datasets()

    @classmethod
    def clear_cache(cls):
        cls._cached_waves = None
        cls._cached_currents = None

    def _load_datasets(self):
        if AStarWeatherRouter._cached_waves is None:
            if os.path.exists(self.waves_path):
                AStarWeatherRouter._cached_waves = xr.open_dataset(self.waves_path).load()
            else:
                raise FileNotFoundError(f"Wave NetCDF not found at {self.waves_path}")

        if AStarWeatherRouter._cached_currents is None:
            if os.path.exists(self.currents_path):
                AStarWeatherRouter._cached_currents = xr.open_dataset(self.currents_path).load()
            else:
                raise FileNotFoundError(f"Current NetCDF not found at {self.currents_path}")

        self.waves = AStarWeatherRouter._cached_waves
        self.currents = AStarWeatherRouter._cached_currents

        # Grid coordinate dimensions
        self.lats = self.waves.latitude.values
        self.lons = self.waves.longitude.values
        self.times = self.waves.time.values

        # Bounding box of the metocean grid
        self.lat_min, self.lat_max = float(self.lats.min()), float(self.lats.max())
        self.lon_min, self.lon_max = float(self.lons.min()), float(self.lons.max())

    def in_bounds(self, lat: float, lon: float) -> bool:
        """Checks if coordinates fall inside our Balearic high-resolution forecast domain."""
        return (self.lat_min <= lat <= self.lat_max) and (self.lon_min <= lon <= self.lon_max)

    def _find_nearest_lat_idx(self, lat: float) -> int:
        return int(np.abs(self.lats - lat).argmin())

    def _find_nearest_lon_idx(self, lon: float) -> int:
        return int(np.abs(self.lons - lon).argmin())

    def _snap_to_water(self, lat: float, lon: float) -> tuple[int, int]:
        """
        Maps a coordinate to the nearest grid index that is actually water (not NaN in wave matrix).
        Uses BFS to expand outward from nearest coordinate index until water is found.
        """
        start_lat_idx = self._find_nearest_lat_idx(lat)
        start_lon_idx = self._find_nearest_lon_idx(lon)
        
        wave_height_matrix = self.waves.VHM0.values
        num_lats, num_lons = wave_height_matrix.shape[1], wave_height_matrix.shape[2]
        
        # Check if the direct mapping is already water
        if not np.isnan(wave_height_matrix[0, start_lat_idx, start_lon_idx]):
            return start_lat_idx, start_lon_idx
            
        # BFS to find the closest water cell in index distance
        queue = [(start_lat_idx, start_lon_idx)]
        visited = {(start_lat_idx, start_lon_idx)}
        
        while queue:
            curr_lat, curr_lon = queue.pop(0)
            
            # Check 8-connected neighbors
            for d_lat, d_lon in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                n_lat = curr_lat + d_lat
                n_lon = curr_lon + d_lon
                
                if 0 <= n_lat < num_lats and 0 <= n_lon < num_lons:
                    if (n_lat, n_lon) not in visited:
                        visited.add((n_lat, n_lon))
                        if not np.isnan(wave_height_matrix[0, n_lat, n_lon]):
                            return n_lat, n_lon
                        queue.append((n_lat, n_lon))
                        
        # Fallback to the original mapping if no water cell is found (unlikely)
        return start_lat_idx, start_lon_idx

    @staticmethod
    def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Computes great-circle distance between two points in nautical miles.
        """
        R = 3440.065  # Earth radius in nautical miles
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _segment_crosses_land(self, p1: dict, p2: dict) -> bool:
        """
        Checks if the straight line segment between p1 and p2 crosses any land cells.
        Samples points along the line segment at regular intervals.
        """
        lat1, lon1 = p1["lat"], p1["lng"]
        lat2, lon2 = p2["lat"], p2["lng"]
        
        d = math.sqrt((lat2 - lat1)**2 + (lon2 - lon1)**2)
        if d == 0.0:
            return False
            
        # Step size of approx 0.015 degrees (well under the grid cell size of ~0.0417 degrees)
        # to ensure we don't skip over any land/shallow grid cells.
        step_size = 0.015
        steps = max(2, int(math.ceil(d / step_size)))
        
        wave_height_matrix = self.waves.VHM0.values
        
        for k in range(1, steps):
            t = k / steps
            lat = lat1 + t * (lat2 - lat1)
            lon = lon1 + t * (lon2 - lon1)
            
            lat_idx = self._find_nearest_lat_idx(lat)
            lon_idx = self._find_nearest_lon_idx(lon)
            
            if np.isnan(wave_height_matrix[0, lat_idx, lon_idx]):
                return True
                
        return False

    def _simplify_waypoints(self, points: list[dict], epsilon: float = 0.015) -> list[dict]:
        """
        Simplifies a 2D line of lat/lng points using the Douglas-Peucker algorithm.
        epsilon: Tolerance in degrees (default 0.015 is approx 0.9 nm).
        Also validates that no simplified segment crosses land, falling back to split recursively.
        """
        if len(points) < 3:
            return points

        def perpendicular_distance(p, p1, p2):
            x, y = p["lng"], p["lat"]
            x1, y1 = p1["lng"], p1["lat"]
            x2, y2 = p2["lng"], p2["lat"]
            
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0.0 and dy == 0.0:
                return math.sqrt((x - x1)**2 + (y - y1)**2)
                
            numerator = abs(dy * x - dx * y + x2 * y1 - y2 * x1)
            denominator = math.sqrt(dx**2 + dy**2)
            return numerator / denominator

        dmax = 0.0
        index = 0
        end = len(points) - 1

        for i in range(1, end):
            d = perpendicular_distance(points[i], points[0], points[end])
            if d > dmax:
                index = i
                dmax = d

        if dmax > epsilon or self._segment_crosses_land(points[0], points[end]):
            split_idx = index if index > 0 else len(points) // 2
            results1 = self._simplify_waypoints(points[:split_idx+1], epsilon)
            results2 = self._simplify_waypoints(points[split_idx:], epsilon)
            return results1[:-1] + results2
        else:
            return [points[0], points[end]]

    def find_route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        departure_dt = None,
    ) -> dict:
        """
        Runs the 4D A* weather routing algorithm.
        Returns a dictionary containing waypoints, distance, and duration.
        """
        if not (self.in_bounds(origin_lat, origin_lon) and self.in_bounds(dest_lat, dest_lon)):
            raise ValueError("Coordinates are out of the Balearic forecast grid bounds.")

        # Map start/end coordinates to the nearest navigable (water) grid indices
        start_lat_idx, start_lon_idx = self._snap_to_water(origin_lat, origin_lon)
        goal_lat_idx, goal_lon_idx = self._snap_to_water(dest_lat, dest_lon)

        start_state = (start_lat_idx, start_lon_idx)
        goal_state = (goal_lat_idx, goal_lon_idx)

        # Priority Queue holds: (f_score, accum_cost, current_lat_idx, current_lon_idx)
        open_set = []
        heapq.heappush(open_set, (0.0, 0.0, start_lat_idx, start_lon_idx))

        # Tracking scores: State -> value
        # accum_cost is the weighted cost minimized by A*
        accum_costs = {start_state: 0.0}
        # elapsed_hours tracks the physical duration (in hours) along the path
        elapsed_hours = {start_state: 0.0}
        
        came_from = {}

        # If departure_dt is provided, compute start_time_idx (the starting offset)
        start_time_idx = 0
        if departure_dt is not None:
            dep_time = pd.to_datetime(departure_dt).tz_localize(None)
            base_time = pd.to_datetime(self.times[0]).tz_localize(None)
            diff_hours = (dep_time - base_time).total_seconds() / 3600.0
            start_time_idx = max(0, int(round(diff_hours)))

        # Pre-cache coordinates to speed up indexing in the loop
        lat_values = self.lats
        lon_values = self.lons
        num_lats = len(self.lats)
        num_lons = len(self.lons)
        max_time_idx = len(self.times) - 1

        # A* Admissible Heuristic: Great-Circle travel time at maximum theoretical speed
        # Maximum typical current is ~2.0 knots to keep heuristic admissible
        max_speed_heuristic = self.vessel_speed + 2.0
        def heuristic(state):
            lat_idx, lon_idx = state
            d = self.haversine(lat_values[lat_idx], lon_values[lon_idx], lat_values[goal_lat_idx], lon_values[goal_lon_idx])
            return d / max_speed_heuristic

        # Extract matrices for direct Numpy memory indexing
        wave_height_matrix = self.waves.VHM0.values
        wave_dir_matrix = self.waves.VMDR.values
        uo_matrix = self.currents.uo.values
        # Note: current file longitude might be 85 vs wave file 84. Ensure boundary safety on indexing current
        current_lons_len = self.currents.longitude.shape[0]
        vo_matrix = self.currents.vo.values

        # Extra matrices for Tp peak period heuristic
        wave_height_matrix_ww = self.waves.VHM0_WW.values if "VHM0_WW" in self.waves else None
        wave_height_matrix_sw1 = self.waves.VHM0_SW1.values if "VHM0_SW1" in self.waves else None
        vtpk_matrix = self.waves.VTPK.values if "VTPK" in self.waves else None

        # Moore neighborhood movements (8 directions)
        moves = [
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1)
        ]

        while open_set:
            _, current_accum_cost, lat_idx, lon_idx = heapq.heappop(open_set)
            current_state = (lat_idx, lon_idx)

            # Reached goal
            if current_state == goal_state:
                # Reconstruct path
                path = [current_state]
                while current_state in came_from:
                    current_state = came_from[current_state]
                    path.append(current_state)
                path.reverse()

                # Build coordinate waypoints
                waypoints = [{"lat": float(lat_values[p[0]]), "lng": float(lon_values[p[1]])} for p in path]
                
                # Apply path simplification to remove grid zig-zags
                simplified = self._simplify_waypoints(waypoints, epsilon=0.015)

                # Keep snapped endpoints on water, and prep/append original coordinates if different
                final_waypoints = []
                orig_point = {"lat": float(origin_lat), "lng": float(origin_lon)}
                if abs(orig_point["lat"] - simplified[0]["lat"]) > 1e-5 or abs(orig_point["lng"] - simplified[0]["lng"]) > 1e-5:
                    final_waypoints.append(orig_point)
                    
                final_waypoints.extend(simplified)
                
                dest_point = {"lat": float(dest_lat), "lng": float(dest_lon)}
                if abs(dest_point["lat"] - simplified[-1]["lat"]) > 1e-5 or abs(dest_point["lng"] - simplified[-1]["lng"]) > 1e-5:
                    if abs(dest_point["lat"] - final_waypoints[-1]["lat"]) > 1e-5 or abs(dest_point["lng"] - final_waypoints[-1]["lng"]) > 1e-5:
                        final_waypoints.append(dest_point)

                # Calculate final precise distance of the prepended/appended simplified path
                final_dist_nm = sum(
                    self.haversine(final_waypoints[i]["lat"], final_waypoints[i]["lng"], final_waypoints[i+1]["lat"], final_waypoints[i+1]["lng"])
                    for i in range(len(final_waypoints) - 1)
                )
                
                # Estimated duration is elapsed hours to goal state + any prepended/appended segment transit hours at vessel speed
                d_start = self.haversine(float(origin_lat), float(origin_lon), lat_values[start_lat_idx], lon_values[start_lon_idx])
                d_goal = self.haversine(lat_values[goal_lat_idx], lon_values[goal_lon_idx], float(dest_lat), float(dest_lon))
                final_duration_h = elapsed_hours[goal_state] + (d_start + d_goal) / self.vessel_speed

                return {
                    "waypoints": final_waypoints,
                    "distance_nm": final_dist_nm,
                    "estimated_time_h": final_duration_h,
                    "source_tag": "astar_weather_route_v1",
                }

            current_time = elapsed_hours[current_state]
            current_lat = lat_values[lat_idx]
            current_lon = lon_values[lon_idx]

            # Determine the appropriate time coordinate index based on physical duration elapsed
            time_idx = min(start_time_idx + int(math.floor(current_time)), max_time_idx)

            for d_lat, d_lon in moves:
                n_lat_idx = lat_idx + d_lat
                n_lon_idx = lon_idx + d_lon

                if not (0 <= n_lat_idx < num_lats and 0 <= n_lon_idx < num_lons):
                    continue

                neighbor_state = (n_lat_idx, n_lon_idx)
                n_lat = lat_values[n_lat_idx]
                n_lon = lon_values[n_lon_idx]

                # Sample wave height and verify navigability (Land/Safety bounds)
                H = wave_height_matrix[time_idx, n_lat_idx, n_lon_idx]
                if np.isnan(H):  # Land cell
                    continue
                if H > self.max_wave_height:  # Over safe wave comfort limit
                    continue

                # Geodesic distance in nm
                step_dist = self.haversine(current_lat, current_lon, n_lat, n_lon)

                # Vector direction unit vector
                dx = n_lon - current_lon
                dy = n_lat - current_lat
                step_len = math.sqrt(dx**2 + dy**2)
                if step_len == 0.0:
                    continue
                ux = dx / step_len
                uy = dy / step_len

                # Sample and project ocean current vectors (converted to knots: 1 m/s = 1.94384 knots)
                c_lon_idx = min(n_lon_idx, current_lons_len - 1)
                u_c = uo_matrix[time_idx, n_lat_idx, c_lon_idx]
                v_c = vo_matrix[time_idx, n_lat_idx, c_lon_idx]

                if np.isnan(u_c) or np.isnan(v_c):
                    u_c, v_c = 0.0, 0.0
                else:
                    u_c = float(u_c) * 1.94384
                    v_c = float(v_c) * 1.94384

                # Projection dot product
                c_proj = u_c * ux + v_c * uy

                # Compute peak wave period Tp
                if vtpk_matrix is not None:
                    Tp = vtpk_matrix[time_idx, n_lat_idx, n_lon_idx]
                    if np.isnan(Tp):
                        Tp = 4.0
                else:
                    # Physical heuristic for Mediterranean wave period approximation
                    ww = wave_height_matrix_ww[time_idx, n_lat_idx, n_lon_idx] if wave_height_matrix_ww is not None else 0.0
                    sw1 = wave_height_matrix_sw1[time_idx, n_lat_idx, n_lon_idx] if wave_height_matrix_sw1 is not None else 0.0
                    if ww > sw1 or sw1 < 0.2:
                        Tp = 4.0  # Wind-sea dominated (steep wave chop)
                    else:
                        Tp = 6.0  # Swell-dominated (longer period)

                # Apply speed degradation penalty: If small vessel (< 20m), Hs > 1m, and Tp < 5s, reduce cruising speed by 20%
                current_speed = self.vessel_speed
                if self.vessel_profile.length_over_all_m < 20.0 and float(H) > 1.0 and float(Tp) < 5.0:
                    current_speed = self.vessel_speed * 0.8

                # Effective vessel speed (ensure positive and safe)
                v_eff = max(current_speed + c_proj, 1.0)

                # Compute step travel time (hours)
                step_time_h = step_dist / v_eff

                # Compute optimization cost with quadratic wave discomfort penalty
                wave_penalty = self.w_wave * (float(H) ** 2)
                step_cost = step_time_h * (1.0 + wave_penalty)

                # Proposed scores
                tentative_accum_cost = current_accum_cost + step_cost
                tentative_elapsed_hours = current_time + step_time_h

                if neighbor_state not in accum_costs or tentative_accum_cost < accum_costs[neighbor_state]:
                    came_from[neighbor_state] = current_state
                    accum_costs[neighbor_state] = tentative_accum_cost
                    elapsed_hours[neighbor_state] = tentative_elapsed_hours
                    
                    f_score = tentative_accum_cost + heuristic(neighbor_state)
                    heapq.heappush(open_set, (f_score, tentative_accum_cost, n_lat_idx, n_lon_idx))

        raise ValueError("A* Weather Routing failed: no valid path exists between the selected points.")
