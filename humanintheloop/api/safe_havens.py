import os
import json
import math
from typing import Any, Dict, List, Optional
from api.schemas import VesselProfile


class SafeHavenFinder:
    def __init__(self, marinas_path: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if marinas_path is None:
            marinas_path = os.path.join(base_dir, "data", "places", "marinas.json")
            if not os.path.exists(marinas_path):
                # Fallback to seed if merged marinas is not built
                marinas_path = os.path.join(base_dir, "data", "places", "marinas_seed.json")

        self.marinas_path = marinas_path
        self.marinas = self._load_marinas()

    def _load_marinas(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.marinas_path):
            return []
        try:
            with open(self.marinas_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    @staticmethod
    def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Computes great-circle distance between two points in nautical miles."""
        R = 3440.065  # Earth radius in nautical miles
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def find_nearest_refuges_for_route(
        self,
        waypoints: List[Dict[str, float]],
        vessel: VesselProfile,
        num_havens: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Scans all waypoints on a route and finds the nearest safe havens (marinas)
        that can accommodate the vessel's length and draft.
        Returns the top `num_havens` safe havens ordered by their proximity to the route.
        """
        if not waypoints or not self.marinas:
            return []

        qualified_havens = []

        for m in self.marinas:
            # 1. Filter by size constraints
            amenities = m.get("amenities", {})
            max_len = amenities.get("max_length_m", 30.0)
            max_draft = amenities.get("max_draft_m", 4.0)

            if vessel.length_over_all_m > max_len:
                continue
            if vessel.draft_m > max_draft:
                continue

            # 2. Find minimum distance from this marina to any waypoint on the route
            m_lat = m["location"]["latitude"]
            m_lon = m["location"]["longitude"]

            min_dist = float("inf")
            closest_waypoint_idx = -1

            for idx, wp in enumerate(waypoints):
                wp_lat = wp.get("lat") or wp.get("latitude")
                wp_lng = wp.get("lng") or wp.get("lon") or wp.get("longitude")
                if wp_lat is None or wp_lng is None:
                    continue
                dist = self.haversine(m_lat, m_lon, float(wp_lat), float(wp_lng))
                if dist < min_dist:
                    min_dist = dist
                    closest_waypoint_idx = idx

            # Keep track of the safe haven with distance metrics
            haven_copy = dict(m)
            haven_copy["distance_to_route_nm"] = round(min_dist, 2)
            haven_copy["closest_waypoint_index"] = closest_waypoint_idx
            qualified_havens.append(haven_copy)

        # Sort by proximity to the route
        qualified_havens.sort(key=lambda x: x["distance_to_route_nm"])

        return qualified_havens[:num_havens]
