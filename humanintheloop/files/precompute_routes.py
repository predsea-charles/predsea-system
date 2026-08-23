"""
precompute_routes.py — PredSea Overnight Route Precomputation

Runs nightly via GitHub Actions or Cloud Scheduler.
Builds the maritime routing grid from the latest Copernicus forecast,
solves all canonical Balearic route pairs for each priority mode,
and writes results to GCS and optionally BigQuery.

Usage:
    python precompute_routes.py \
        --waves gs://predsea-daily-outputs/copernicus/waves_latest.nc \
        --currents gs://predsea-daily-outputs/copernicus/currents_latest.nc \
        --output-dir gs://predsea-daily-outputs/routes \
        --date 2026-06-14

    # Local test with local files:
    python precompute_routes.py \
        --waves /tmp/waves.nc \
        --currents /tmp/currents.nc \
        --output-dir /tmp/routes \
        --date 2026-06-14 \
        --dry-run
"""

import argparse
import json
import logging
import pickle
import os
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from route_graph import MaritimeGrid
from route_solver import RouteSolver

HUMANINTHELOOP_DIR = Path(__file__).resolve().parent.parent
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("precompute_routes")


# ---------------------------------------------------------------------------
# Canonical places
# ---------------------------------------------------------------------------
#
# This used to be the only source of truth for what gets precomputed, paired
# via combinations() -- i.e. every place against every other place. That
# quietly missed most of the mainland/Sardinia/Italy routes.json entries
# (Genoa, Marseille, Toulon, Cagliari, Naples, Palermo, Messina, Montpellier,
# Tarragona, Palamos were never in here), and blindly adding all of those here
# would multiply the nightly solve count several times over for pairs nobody
# actually asks for (e.g. "Port Adriano -> Messina").
#
# Instead: keep this core Balearic cluster fully cross-connected (unchanged
# behavior), and separately pull in exactly the additional pairs that
# routes.json actually defines -- so precompute tracks the product's real
# route inventory (including new additions like Monaco) instead of a third,
# hand-maintained place list.

CANONICAL_PLACES = {
    "palma":       (39.5696,  2.6502),
    "port_de_palma": (39.5518, 2.6259),
    "port_adriano": (39.4990, 2.4780),
    "can_pastilla": (39.5370, 2.7200),
    "ibiza":       (38.9081,  1.4207),
    "formentera":  (38.7012,  1.4818),
    "menorca":     (39.9864,  4.1592),
    "ciutadella":  (40.0000,  3.8303),
    "alcudia":     (39.8531,  3.1215),
    "soller":      (39.7957,  2.6897),
    "portocolom":  (39.5197,  3.2563),
    "cabrera":     (39.1447,  2.9322),
    "barcelona":   (41.3851,  2.1734),
    "valencia":    (39.4699, -0.3763),
}


def additional_pairs_from_routes_json():
    """Resolve every routes.json entry's origin/destination to canonical place
    ids via place_registry, returning {place_id: (lat, lon)} for any place not
    already in CANONICAL_PLACES, plus the list of (origin_id, destination_id)
    pairs those routes actually need. Best-effort: any entry that can't be
    resolved (e.g. place_registry unavailable) is skipped, not fatal.
    """
    extra_places = {}
    extra_pairs = []
    routes_path = HUMANINTHELOOP_DIR / "routes.json"
    try:
        import place_registry
        routes = json.loads(routes_path.read_text(encoding="utf-8"))
    except Exception as error:
        logger.warning("Could not derive extra route pairs from routes.json: %s", error)
        return extra_places, extra_pairs

    for route in routes.values():
        try:
            origin = route["origin"]
            destination = route["destination"]
            origin_id = place_registry.default_place_id_for_query(origin["name"])
            destination_id = place_registry.default_place_id_for_query(destination["name"])
            if not origin_id or not destination_id or origin_id == destination_id:
                continue
            extra_places.setdefault(origin_id, (float(origin["latitude"]), float(origin["longitude"])))
            extra_places.setdefault(destination_id, (float(destination["latitude"]), float(destination["longitude"])))
            extra_pairs.append((origin_id, destination_id))
            extra_pairs.append((destination_id, origin_id))
        except Exception as error:
            logger.warning("Skipping routes.json entry %r: %s", route.get("id"), error)

    # Places already covered by the core cluster don't need re-adding.
    extra_places = {
        place_id: coords
        for place_id, coords in extra_places.items()
        if place_id not in CANONICAL_PLACES
    }
    return extra_places, extra_pairs


# Vessel profiles for precomputation
VESSEL_PROFILES = [
    {"vessel_class": "small",  "vessel_speed_kn": 8.0},
    {"vessel_class": "medium", "vessel_speed_kn": 10.0},
    {"vessel_class": "large",  "vessel_speed_kn": 12.0},
]

# Priority modes
PRIORITIES = ["time", "comfort", "safety"]


# ---------------------------------------------------------------------------
# GCS helpers (simple wrapper — avoids a hard dependency on google-cloud-storage
# when running locally)
# ---------------------------------------------------------------------------

def is_gcs_path(path: str) -> bool:
    return path.startswith("gs://")


def write_output(content: bytes, path: str, dry_run: bool = False) -> None:
    if dry_run:
        logger.info("[DRY RUN] Would write %d bytes to %s", len(content), path)
        return

    if is_gcs_path(path):
        try:
            from google.cloud import storage
            bucket_name, blob_name = path[5:].split("/", 1)
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(content)
            logger.info("Written to GCS: %s", path)
        except Exception as e:
            logger.error("GCS write failed for %s: %s", path, e)
            raise
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(content)
        logger.info("Written locally: %s", path)


def read_netcdf_path(path: str) -> str:
    """
    If path is a GCS URI, download to /tmp and return local path.
    Otherwise return as-is.
    """
    if not is_gcs_path(path):
        return path

    try:
        from google.cloud import storage
        bucket_name, blob_name = path[5:].split("/", 1)
        local_path = f"/tmp/{Path(blob_name).name}"
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.download_to_filename(local_path)
        logger.info("Downloaded %s -> %s", path, local_path)
        return local_path
    except Exception as e:
        logger.error("GCS download failed for %s: %s", path, e)
        raise


# ---------------------------------------------------------------------------
# Main precompute logic
# ---------------------------------------------------------------------------

def precompute(
    waves_path: str,
    currents_path: str,
    output_dir: str,
    date: str,
    dry_run: bool = False,
    forecast_run_utc: str = "",
) -> dict:
    """
    Precompute all route pairs for all priorities and vessel classes.
    Returns a summary dict.
    """
    computed_at = datetime.now(timezone.utc).isoformat()

    # Download NetCDF if needed
    waves_local    = read_netcdf_path(waves_path)
    currents_local = read_netcdf_path(currents_path)
    waves_local = os.path.abspath(waves_local)
    currents_local = os.path.abspath(currents_local)

    # Build all priority graphs — one grid load, three graph builds
    logger.info("Loading Copernicus grid from: %s", waves_local)
    grid = MaritimeGrid.from_netcdf(waves_local, currents_local)
    grid.build_vertex_index()

    # Core Balearic cluster stays fully cross-connected (unchanged behavior).
    place_ids = list(CANONICAL_PLACES.keys())
    route_pairs = []
    for a, b in combinations(place_ids, 2):
        route_pairs.append((a, b))
        route_pairs.append((b, a))

    # Additionally, solve exactly the pairs routes.json actually defines for
    # places outside that core cluster (Monaco, Genoa, Marseille, Cagliari,
    # etc.) instead of cross-connecting everything, to avoid an unnecessary
    # combinatorial blow-up for pairs no one queries.
    extra_places, extra_pairs = additional_pairs_from_routes_json()
    all_places = dict(CANONICAL_PLACES)
    all_places.update(extra_places)
    for pair in extra_pairs:
        if pair not in route_pairs:
            route_pairs.append(pair)

    if extra_places:
        logger.info(
            "Added %d extra places and %d extra route pairs from routes.json: %s",
            len(extra_places), len(extra_pairs), sorted(extra_places),
        )

    logger.info(
        "Precomputing %d route pairs × %d priorities × %d vessel classes = %d solves",
        len(route_pairs), len(PRIORITIES), len(VESSEL_PROFILES),
        len(route_pairs) * len(PRIORITIES) * len(VESSEL_PROFILES),
    )

    all_results = {}
    summary = {"date": date, "computed_at_utc": computed_at, "routes": []}

    for priority in PRIORITIES:
        logger.info("--- Priority: %s ---", priority)

        # Rebuild graph for this priority using medium vessel as default
        grid.build_graph(
            priority=priority,
            vessel_class="medium",
            vessel_speed_kn=10.0,
        )

        for vessel_profile in VESSEL_PROFILES:
            vessel_class    = vessel_profile["vessel_class"]
            vessel_speed_kn = vessel_profile["vessel_speed_kn"]

            # For safety priority, rebuild graph with correct vessel class thresholds
            if priority == "safety":
                grid.build_graph(
                    priority=priority,
                    vessel_class=vessel_class,
                    vessel_speed_kn=vessel_speed_kn,
                )

            solver = RouteSolver(grid)

            for origin_id, dest_id in route_pairs:
                origin_lat, origin_lon = all_places[origin_id]
                dest_lat,   dest_lon   = all_places[dest_id]

                route_key = f"{origin_id}__{dest_id}__{priority}__{vessel_class}"

                result = solver.solve(
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                    destination_lat=dest_lat,
                    destination_lon=dest_lon,
                    origin_place_id=origin_id,
                    destination_place_id=dest_id,
                    vessel_speed_kn=vessel_speed_kn,
                    forecast_run_utc=forecast_run_utc,
                    computed_at_utc=computed_at,
                )

                if result is None:
                    logger.warning("No result for %s", route_key)
                    continue

                all_results[route_key] = result.to_dict()

                summary["routes"].append({
                    "key": route_key,
                    "origin": origin_id,
                    "destination": dest_id,
                    "priority": priority,
                    "vessel_class": vessel_class,
                    "distance_nm": result.distance_nm,
                    "estimated_time_h": result.estimated_time_h,
                    "avg_wave_hs_m": result.avg_wave_hs_m,
                    "max_wave_hs_m": result.max_wave_hs_m,
                })

                logger.info(
                    "  %s -> %s [%s/%s]: %.1f nm, %.2f h, wave avg %.2f m",
                    origin_id, dest_id, priority, vessel_class,
                    result.distance_nm, result.estimated_time_h, result.avg_wave_hs_m,
                )

    # Write full results as JSON
    results_path = f"{output_dir}/{date}/route_results.json"
    write_output(
        json.dumps(all_results, indent=2).encode(),
        results_path,
        dry_run=dry_run,
    )

    # Write summary
    summary_path = f"{output_dir}/{date}/route_summary.json"
    write_output(
        json.dumps(summary, indent=2).encode(),
        summary_path,
        dry_run=dry_run,
    )

    logger.info(
        "Precompute complete: %d routes written to %s",
        len(all_results), output_dir,
    )

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="PredSea route precomputation")
    parser.add_argument("--waves",    required=True, help="Path or GCS URI to Copernicus waves NetCDF")
    parser.add_argument("--currents", required=True, help="Path or GCS URI to Copernicus currents NetCDF")
    parser.add_argument("--output-dir", required=True, help="Local dir or GCS prefix for output JSON")
    parser.add_argument("--date",     required=True, help="Date string YYYY-MM-DD for output path")
    parser.add_argument("--forecast-run-utc", default="", help="ISO timestamp of the forecast run used")
    parser.add_argument("--dry-run",  action="store_true", help="Compute but do not write output")
    args = parser.parse_args()

    summary = precompute(
        waves_path=args.waves,
        currents_path=args.currents,
        output_dir=args.output_dir,
        date=args.date,
        dry_run=args.dry_run,
        forecast_run_utc=args.forecast_run_utc,
    )

    logger.info("Summary: %d routes computed", len(summary.get("routes", [])))


if __name__ == "__main__":
    main()
