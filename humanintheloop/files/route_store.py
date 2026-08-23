"""
route_store.py — PredSea Precomputed Route Store

Loads the nightly precomputed route JSON and exposes a simple
lookup interface for the API layer.

The API calls RouteStore.get(...) — no Dijkstra at request time.
"""

import json
import logging
from datetime import date as date_type, datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RouteStore:
    """
    In-memory store of precomputed route results.

    Load once at API startup, refresh daily when a new precompute
    output is available.
    """

    def __init__(self):
        self._results: dict = {}
        self._loaded_date: Optional[str] = None
        self._loaded_at: Optional[str] = None

    def load_from_file(self, path: str) -> None:
        """Load a route_results.json produced by precompute_routes.py."""
        with open(path) as f:
            self._results = json.load(f)
        self._loaded_date = Path(path).parent.name  # e.g. "2026-06-14"
        self._loaded_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "RouteStore loaded: %d routes from %s",
            len(self._results), path,
        )

    def load_from_gcs(self, gcs_prefix: str, date_str: str) -> None:
        """Download and load route_results.json from GCS."""
        from google.cloud import storage
        path_in_bucket = f"{date_str}/route_results.json"
        bucket_name, prefix = gcs_prefix[5:].split("/", 1)
        blob_name = f"{prefix}/{path_in_bucket}".lstrip("/")

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        local_path = f"/tmp/route_results_{date_str}.json"
        blob.download_to_filename(local_path)
        self.load_from_file(local_path)

    def get(
        self,
        origin: str,
        destination: str,
        priority: str = "comfort",
        vessel_class: str = "medium",
    ) -> Optional[dict]:
        """
        Look up a precomputed route result.

        Parameters
        ----------
        origin, destination : canonical place_ids
        priority            : "time" | "comfort" | "safety"
        vessel_class        : "small" | "medium" | "large"
        """
        key = f"{origin}__{destination}__{priority}__{vessel_class}"
        result = self._results.get(key)
        if result is None:
            logger.warning("No precomputed route for key: %s", key)
        return result

    def get_distance_nm(self, origin: str, destination: str) -> Optional[float]:
        """
        Convenience: return straight optimal distance for the time-priority
        medium vessel route (best proxy for true nautical distance).
        """
        result = self.get(origin, destination, priority="time", vessel_class="medium")
        if result:
            return result.get("distance_nm")
        return None

    def get_typical_time_h(
        self,
        origin: str,
        destination: str,
        vessel_class: str = "medium",
    ) -> Optional[float]:
        result = self.get(origin, destination, priority="time", vessel_class=vessel_class)
        if result:
            return result.get("estimated_time_h")
        return None

    def list_routes(self) -> list[dict]:
        """Return a summary list of all available precomputed routes."""
        seen = set()
        out = []
        for key, val in self._results.items():
            pair_key = f"{val['origin_place_id']}__{val['destination_place_id']}"
            if pair_key not in seen:
                seen.add(pair_key)
                out.append({
                    "origin": val["origin_place_id"],
                    "destination": val["destination_place_id"],
                    "distance_nm": val.get("distance_nm"),
                })
        return sorted(out, key=lambda x: (x["origin"], x["destination"]))

    def status(self) -> dict:
        return {
            "loaded_date": self._loaded_date,
            "loaded_at": self._loaded_at,
            "route_count": len(self._results),
        }


# ---------------------------------------------------------------------------
# Suggested API endpoint handlers
# ---------------------------------------------------------------------------

"""
Add these to your existing FastAPI / Flask app:

from route_store import RouteStore

route_store = RouteStore()

# Load at startup (or refresh daily):
route_store.load_from_gcs("gs://predsea-daily-outputs/routes", date_str="latest")


@app.get("/routes/optimal/{origin}/{destination}")
def get_optimal_route(
    origin: str,
    destination: str,
    priority: str = "comfort",
    vessel_class: str = "medium",
):
    result = route_store.get(origin, destination, priority, vessel_class)
    if result is None:
        return {"error": "Route not available", "origin": origin, "destination": destination}, 404

    # Return the API-friendly shape (no full waypoint list unless requested)
    return {
        "origin": result["origin_place_id"],
        "destination": result["destination_place_id"],
        "priority": result["priority"],
        "vessel_class": result["vessel_class"],
        "distance_nm": result["distance_nm"],
        "estimated_time_h": result["estimated_time_h"],
        "avg_wave_hs_m": result["avg_wave_hs_m"],
        "max_wave_hs_m": result["max_wave_hs_m"],
        "avg_current_kn": result["avg_current_kn"],
        "favourable_current_pct": result["favourable_current_pct"],
        "forecast_run_utc": result["forecast_run_utc"],
        "computed_at_utc": result["computed_at_utc"],
        "waypoints": result["waypoints"],  # lat/lon list for map rendering
    }


@app.get("/places/distance")
def get_distance(origin: str, destination: str):
    dist = route_store.get_distance_nm(origin, destination)
    if dist is None:
        return {"error": "Distance not available"}, 404
    return {
        "origin": origin,
        "destination": destination,
        "distance_nm": dist,
        "source": "precomputed_optimal_route",
    }


@app.get("/routes/optimal/status")
def route_status():
    return route_store.status()
"""
