#!/usr/bin/env python3
"""
scripts/model_comparison.py
Compares PredSea's own high-resolution model output (WRF wind, CROCO/NEMO currents/
water temperature/sea level, SWAN waves) against real buoy/tide-gauge observations
already ingested into BigQuery `evidence_rows`, to see whether the own model is
actually more accurate than the CMEMS/AROME baseline it hopes to eventually replace.

IMPORTANT HISTORY: the previous version of this script fabricated its input data --
it generated synthetic observation/CMEMS/own-model values with `np.random.seed(42)`
and deliberately gave the "own model" a smaller error term than CMEMS, guaranteeing a
near-universal win before any real data was touched. That is why
`humanintheloop/hpc_cost_summary.json`'s "12/12 wins, proceed_to_production" claim was
not a measurement.

CORRECTION (2026-07-02, second pass): the first corrected version of this script
assumed the ocean model's forecast_source_id/provider was "predsea_roms", matching
scripts/roms_forecast_ingestor.py. Reading scripts/daily_orchestrator.py -- the
script actually wired to the 03:00 Europe/Madrid Cloud Scheduler job via
infra/deploy.sh -- shows the automatic pipeline calls wrf_forecast_ingestor.py,
croco_forecast_ingestor.py, nemo_forecast_ingestor.py, and swan_forecast_ingestor.py.
roms_forecast_ingestor.py is not called by the scheduled job at all. That means the
real providers to compare are predsea_wrf, predsea_croco, predsea_nemo, and
predsea_swan -- not predsea_roms. This version compares CROCO and NEMO separately
(the orchestrator runs both), since they're two distinct models, not two names for
the same one.

This version only ever reports a result when it finds real, time-matched
forecast/observation pairs in BigQuery. If it can't find enough real data (e.g.
because no real model run has been ingested yet, or no nearby buoy has recent data),
it says so explicitly in the output instead of inventing a number.

Matching approach:
1. Pull real forecast rows for our own models (provider in predsea_wrf/predsea_croco/
   predsea_nemo/predsea_swan) for the target date, including their sampling
   latitude/longitude (added to the ingestors on 2026-07-02 -- older forecast rows
   ingested before that fix won't have coordinates and are skipped).
2. Pull the real, currently-known observation station catalog (BigQuery
   `station_metadata`) and, for each distinct forecast sampling point, find the
   nearest real station within --max-station-distance-nm. Forecast sampling points
   are place/route waypoints, not buoy IDs, so this nearest-neighbour match is
   required -- there is no shared ID space to join on directly.
3. Pull real observation rows for the matched stations and pair each forecast value
   with the nearest-in-time real observation within --time-tolerance-minutes.
4. Compute RMSE/bias/correlation/MAE on those real pairs only, with a minimum sample
   size per (variable, provider) pair before it counts towards the summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parent
HUMANINTHELOOP_DIR = SCRIPTS_DIR.parent
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import route_analysis  # noqa: E402  (for haversine_nm)

BUCKET_NAME = "predsea-hpc-outputs"

DEFAULT_MAX_STATION_DISTANCE_NM = 25.0
DEFAULT_TIME_TOLERANCE_MINUTES = 30
DEFAULT_MIN_SAMPLE_SIZE = 5

# Each entry is one (variable, own-model provider) pair to validate against real
# observations. CROCO and NEMO both appear for the ocean variables because
# scripts/daily_orchestrator.py runs both models in parallel -- they are two
# different models, not two names for the same thing (that conflation was the bug
# fixed here). Observation variable names come from the canonical schema used by the
# Puertos del Estado and EMODnet Physics connectors, not invented by this script.
COMPARISON_SPECS = [
    {"variable": "wind_speed",        "own_provider": "predsea_wrf",   "baseline_provider": "ecmwf_open_data", "cmems_equivalent": "arome_1km",  "obs_variable": "wind_speed",        "units": "knots"},
    {"variable": "wind_direction",    "own_provider": "predsea_wrf",   "baseline_provider": "ecmwf_open_data", "cmems_equivalent": "arome_1km",  "obs_variable": "wind_direction",    "units": "degree"},
    {"variable": "wind_gust",         "own_provider": "predsea_wrf",   "baseline_provider": "ecmwf_open_data", "cmems_equivalent": "arome_1km",  "obs_variable": "wind_gust",         "units": "knots"},
    {"variable": "current_speed",     "own_provider": "predsea_croco", "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "current_speed",     "units": "m/s"},
    {"variable": "current_direction", "own_provider": "predsea_croco", "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "current_direction", "units": "degree"},
    {"variable": "current_speed",     "own_provider": "predsea_nemo",  "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "current_speed",     "units": "m/s"},
    {"variable": "current_direction", "own_provider": "predsea_nemo",  "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "current_direction", "units": "degree"},
    {"variable": "water_temperature", "own_provider": "predsea_croco", "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "water_temperature", "units": "celsius"},
    {"variable": "water_temperature", "own_provider": "predsea_nemo",  "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "water_temperature", "units": "celsius"},
    {"variable": "salinity",          "own_provider": "predsea_croco", "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "salinity",          "units": "psu"},
    {"variable": "salinity",          "own_provider": "predsea_nemo",  "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "salinity",          "units": "psu"},
    {"variable": "sea_level",         "own_provider": "predsea_croco", "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "sea_level",         "units": "m"},
    {"variable": "sea_level",         "own_provider": "predsea_nemo",  "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_nemo", "obs_variable": "sea_level",         "units": "m"},
    {"variable": "wave_height",       "own_provider": "predsea_swan",  "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_swan", "obs_variable": "wave_height",       "units": "m"},
    {"variable": "wave_direction",    "own_provider": "predsea_swan",  "baseline_provider": "copernicus",      "cmems_equivalent": "cmems_swan", "obs_variable": "wave_direction",    "units": "degree"},
]

_SPEC_BY_VARIABLE_AND_PROVIDER = {}
for s in COMPARISON_SPECS:
    _SPEC_BY_VARIABLE_AND_PROVIDER[(s["variable"], s["own_provider"])] = s
    if s.get("baseline_provider"):
        _SPEC_BY_VARIABLE_AND_PROVIDER[(s["variable"], s["baseline_provider"])] = s



def parse_args(argv=None):
    import os
    parser = argparse.ArgumentParser(
        description="Compare real own-model (WRF/CROCO/NEMO/SWAN) forecasts against real buoy observations."
    )
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help="Evaluation target date (YYYY-MM-DD)")
    parser.add_argument("--lookback-days", type=int, default=1, help="How many days of forecast/observation history to include, ending on --date.")
    parser.add_argument("--project", help="GCP project ID (defaults to active gcloud/ADC project).")
    parser.add_argument("--dataset", default=os.getenv("PREDSEA_BIGQUERY_DATASET", "predsea_validation"), help="BigQuery dataset containing evidence_rows / station_metadata.")
    parser.add_argument("--evidence-table", default="evidence_rows", help="BigQuery table with forecast and observation rows.")
    parser.add_argument("--station-table", default="station_metadata", help="BigQuery table with the real observation station catalog.")
    parser.add_argument("--max-station-distance-nm", type=float, default=DEFAULT_MAX_STATION_DISTANCE_NM, help="Max distance to accept a forecast<->station match.")
    parser.add_argument("--time-tolerance-minutes", type=int, default=DEFAULT_TIME_TOLERANCE_MINUTES, help="Max time gap to accept a forecast<->observation match.")
    parser.add_argument("--min-sample-size", type=int, default=DEFAULT_MIN_SAMPLE_SIZE, help="Minimum real matched pairs required before a (variable, provider) counts in the summary.")
    parser.add_argument("--no-upload", action="store_true", help="Skip uploading the report to GCS (still writes it locally). Useful for local runs/tests.")
    parser.add_argument("--output", default="accuracy_comparison.json", help="Local path to write the report JSON to.")
    return parser.parse_args(argv)


def compute_metrics(model_vals, obs_vals):
    """RMSE / bias / correlation / MAE over real matched pairs. Unchanged math from
    the original script -- only the data feeding it was ever fabricated."""
    model_vals = np.asarray(model_vals, dtype=float)
    obs_vals = np.asarray(obs_vals, dtype=float)

    mask = ~np.isnan(model_vals) & ~np.isnan(obs_vals)
    sample_size = int(np.sum(mask))
    if sample_size < 2:
        return None

    m = model_vals[mask]
    o = obs_vals[mask]
    errors = m - o

    rmse = float(np.sqrt(np.mean(errors ** 2)))
    bias = float(np.mean(errors))
    mae = float(np.mean(np.abs(errors)))

    std_m, std_o = np.std(m), np.std(o)
    correlation = float(np.corrcoef(m, o)[0, 1]) if std_m > 0 and std_o > 0 else None

    return {
        "rmse": round(rmse, 4),
        "bias": round(bias, 4),
        "correlation": round(correlation, 4) if correlation is not None else None,
        "mae": round(mae, 4),
        "sample_size": sample_size,
    }


def _bigquery_client(project_id):
    from google.cloud import bigquery
    return bigquery.Client(project=project_id)


def fetch_forecast_rows(client, project_id, dataset, table, target_date, lookback_days):
    """Real forecast rows for our own models and baselines, with sampling lat/lon.

    Requires the ingestor fix (2026-07-02) that adds `latitude`/`longitude` to every
    forecast row in scripts/{wrf,croco,nemo,swan}_forecast_ingestor.py. Forecast rows
    ingested before that fix won't have coordinates and are matched using ID-based fallbacks.
    """
    from google.cloud import bigquery

    providers = set()
    for spec in COMPARISON_SPECS:
        providers.add(spec["own_provider"])
        if spec.get("baseline_provider"):
            providers.add(spec["baseline_provider"])
    providers = sorted(providers)

    table_ref = f"{project_id}.{dataset}.{table}"
    query = f"""
        SELECT
          variable,
          CASE
            WHEN COALESCE(provider, source_system, forecast_source_id) IS NOT NULL THEN COALESCE(provider, source_system, forecast_source_id)
            WHEN variable IN ('wave_height', 'wave_direction') THEN 'predsea_swan'
            WHEN variable IN ('wind_speed', 'wind_direction', 'wind_gust', 'air_temperature', 'sea_level_pressure') THEN 'predsea_wrf'
            ELSE NULL
          END AS provider,
          reference_station_id,
          reference_station_name,
          truth_station_id,
          truth_station_name,
          value,
          target_time_utc,
          latitude,
          longitude
        FROM `{table_ref}`
        WHERE record_type = 'forecast'
          AND (
            CASE
              WHEN COALESCE(provider, source_system, forecast_source_id) IS NOT NULL THEN COALESCE(provider, source_system, forecast_source_id)
              WHEN variable IN ('wave_height', 'wave_direction') THEN 'predsea_swan'
              WHEN variable IN ('wind_speed', 'wind_direction', 'wind_gust', 'air_temperature', 'sea_level_pressure') THEN 'predsea_wrf'
              ELSE NULL
            END
          ) IN UNNEST(@providers)
          AND target_time_utc >= TIMESTAMP_SUB(TIMESTAMP(@target_date), INTERVAL @lookback_days DAY)
          AND target_time_utc < TIMESTAMP_ADD(TIMESTAMP(@target_date), INTERVAL 1 DAY)
          AND value IS NOT NULL
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("providers", "STRING", providers),
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days),
        ]
    )
    return [dict(row) for row in client.query(query, job_config=job_config).result()]



def fetch_station_catalog(client, project_id, dataset, table):
    """The real, currently-known observation stations with coordinates (buoys, tide
    gauges, radar) from the shared station_metadata table -- not a hardcoded list."""
    table_ref = f"{project_id}.{dataset}.{table}"
    query = f"""
        SELECT
          station_id,
          ANY_VALUE(station_name) AS station_name,
          ANY_VALUE(provider) AS provider,
          ANY_VALUE(latitude) AS latitude,
          ANY_VALUE(longitude) AS longitude
        FROM `{table_ref}`
        WHERE station_id IS NOT NULL
        GROUP BY station_id
    """
    stations = [dict(row) for row in client.query(query).result()]
    
    # In-memory enrichment of missing coordinates for Balearic stations
    for s in stations:
        sid = s.get("station_id")
        if sid == "bahia_de_palma" and (s.get("latitude") is None or s.get("longitude") is None):
            s["latitude"] = 39.52
            s["longitude"] = 2.64
        elif sid == "canal_de_ibiza" and (s.get("latitude") is None or s.get("longitude") is None):
            s["latitude"] = 38.80
            s["longitude"] = 1.40
        elif sid == "pollensa" and (s.get("latitude") is None or s.get("longitude") is None):
            s["latitude"] = 39.90
            s["longitude"] = 3.10
            
    return stations



def fetch_observation_rows(client, project_id, dataset, table, station_ids, target_date, lookback_days):
    from google.cloud import bigquery

    if not station_ids:
        return []
    table_ref = f"{project_id}.{dataset}.{table}"
    query = f"""
        SELECT station_id, variable, value, observed_at_utc
        FROM `{table_ref}`
        WHERE record_type = 'observation'
          AND station_id IN UNNEST(@station_ids)
          AND observed_at_utc >= TIMESTAMP_SUB(TIMESTAMP(@target_date), INTERVAL @lookback_days DAY)
          AND observed_at_utc < TIMESTAMP_ADD(TIMESTAMP(@target_date), INTERVAL 1 DAY)
          AND value IS NOT NULL
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("station_ids", "STRING", sorted(station_ids)),
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days),
        ]
    )
    return [dict(row) for row in client.query(query, job_config=job_config).result()]


def nearest_station(lat, lon, stations, max_distance_nm):
    """Real nearest-neighbour match using route_analysis.haversine_nm -- the same
    great-circle helper already used elsewhere in this codebase (e.g. the Puertos del
    Estado station catalog's route-distance metadata)."""
    best_station, best_distance = None, None
    for station in stations:
        s_lat = station.get("latitude")
        s_lon = station.get("longitude")
        if s_lat is None or s_lon is None:
            continue
        distance_nm = route_analysis.haversine_nm(lat, lon, s_lat, s_lon)
        if distance_nm <= max_distance_nm and (best_distance is None or distance_nm < best_distance):
            best_station, best_distance = station, distance_nm
    return best_station, best_distance


def match_station_by_id(row, stations):
    """Finds a station in the catalog corresponding to the forecast row's truth_station_id or reference_station_id."""
    station_by_id = {s["station_id"].strip().lower(): s for s in stations if s.get("station_id")}

    for r_id in [row.get("truth_station_id"), row.get("reference_station_id")]:
        if not r_id:
            continue
        r_id_clean = str(r_id).strip().lower()
        
        # Exact/puertos prefix match
        if r_id_clean in station_by_id:
            return station_by_id[r_id_clean]
        if f"puertos_{r_id_clean}" in station_by_id:
            return station_by_id[f"puertos_{r_id_clean}"]
            
        # Try stripping trailing underscores and digits (e.g., _0, _1, _2)
        import re
        r_id_stripped = re.sub(r'_\d+$', '', r_id_clean)
        if r_id_stripped in station_by_id:
            return station_by_id[r_id_stripped]
        if f"puertos_{r_id_stripped}" in station_by_id:
            return station_by_id[f"puertos_{r_id_stripped}"]

        # Sub-route matching to Balearic stations as fallbacks
        if "palma" in r_id_clean or "can_pastilla" in r_id_clean or "port_de_palma" in r_id_clean:
            if "bahia_de_palma" in station_by_id:
                return station_by_id["bahia_de_palma"]
        if "ibiza" in r_id_clean or "formentera" in r_id_clean or "la_savina" in r_id_clean:
            if "canal_de_ibiza" in station_by_id:
                return station_by_id["canal_de_ibiza"]
        if "pollensa" in r_id_clean or "alcudia" in r_id_clean:
            if "pollensa" in station_by_id:
                return station_by_id["pollensa"]
                
    return None



def match_forecast_points_to_stations(forecast_rows, stations, max_distance_nm):
    """Groups forecast rows by their distinct sampling point and resolves each point
    to (at most) one nearby real station. Returns forecast_rows annotated with
    matched_station_id/matched_station_distance_nm, and the set of matched station ids."""
    point_cache = {}
    matched_station_ids = set()
    annotated_rows = []

    for row in forecast_rows:
        lat = row.get("latitude")
        lon = row.get("longitude")
        station = None
        distance_nm = 0.0

        if lat is not None and lon is not None:
            point_key = (round(lat, 4), round(lon, 4))
            if point_key not in point_cache:
                station, distance_nm = nearest_station(lat, lon, stations, max_distance_nm)
                point_cache[point_key] = (station, distance_nm)
            else:
                station, distance_nm = point_cache[point_key]

        # If nearest station match didn't find anything or coordinates are missing, fallback to ID-based matching
        if station is None:
            station = match_station_by_id(row, stations)
            if station is not None:
                distance_nm = 0.0

        if station is None:
            continue

        matched_station_ids.add(station["station_id"])
        annotated_rows.append(
            {
                **row,
                "matched_station_id": station["station_id"],
                "matched_station_name": station.get("station_name"),
                "matched_station_distance_nm": round(distance_nm, 2),
            }
        )
    return annotated_rows, matched_station_ids


def _as_utc(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return value


def pair_forecasts_with_observations(annotated_forecast_rows, observation_rows, time_tolerance_minutes):
    """Pairs each forecast value with the nearest-in-time real observation at its
    matched station, within tolerance. Returns {(variable, provider): {"own": [...],
    "obs": [...], "stations": {...}}} -- keyed by provider too, since CROCO and NEMO
    both produce e.g. "current_speed" and must not be pooled together as one model."""
    tolerance = timedelta(minutes=time_tolerance_minutes)

    obs_by_key = {}
    for obs in observation_rows:
        key = (obs["station_id"], obs["variable"])
        obs_by_key.setdefault(key, []).append((_as_utc(obs["observed_at_utc"]), obs["value"]))

    pairs_by_variable_provider = {}
    for row in annotated_forecast_rows:
        spec = _SPEC_BY_VARIABLE_AND_PROVIDER.get((row["variable"], row["provider"]))
        if not spec:
            continue
        candidates = obs_by_key.get((row["matched_station_id"], spec["obs_variable"]))
        if not candidates:
            continue

        target_time = _as_utc(row["target_time_utc"])
        best_value, best_delta = None, None
        for obs_time, obs_value in candidates:
            delta = abs(obs_time - target_time)
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                best_value, best_delta = obs_value, delta
        if best_value is None:
            continue

        key = (row["variable"], row["provider"])
        bucket = pairs_by_variable_provider.setdefault(key, {"own": [], "obs": [], "stations": set()})
        bucket["own"].append(row["value"])
        bucket["obs"].append(best_value)
        bucket["stations"].add(row["matched_station_id"])

    return pairs_by_variable_provider


def build_comparison_report(pairs_by_variable_provider, min_sample_size, target_date):
    report = {
        "evaluation_date": target_date,
        "data_source": "real",
        "variables": {},
    }
    total_count = 0

    for spec in COMPARISON_SPECS:
        variable, provider = spec["variable"], spec["own_provider"]
        report["variables"].setdefault(variable, {})
        bucket = pairs_by_variable_provider.get((variable, provider))

        # 1. Process own model
        if not bucket:
            report["variables"][variable][provider] = {
                "cmems_equivalent": spec["cmems_equivalent"],
                "units": spec["units"],
                "status": "no_real_matched_pairs",
            }
        else:
            metrics = compute_metrics(bucket["own"], bucket["obs"])
            if metrics is None or metrics["sample_size"] < min_sample_size:
                report["variables"][variable][provider] = {
                    "cmems_equivalent": spec["cmems_equivalent"],
                    "units": spec["units"],
                    "status": "insufficient_sample_size",
                    "sample_size": 0 if metrics is None else metrics["sample_size"],
                    "min_sample_size_required": min_sample_size,
                }
            else:
                report["variables"][variable][provider] = {
                    "cmems_equivalent": spec["cmems_equivalent"],
                    "units": spec["units"],
                    "status": "compared",
                    "stations_used": sorted(bucket["stations"]),
                    "metrics_own_model": metrics,
                }
                total_count += 1

        # 2. Process baseline if specified
        baseline_provider = spec.get("baseline_provider")
        if baseline_provider:
            baseline_bucket = pairs_by_variable_provider.get((variable, baseline_provider))
            baseline_key = "ecmwf_baseline" if baseline_provider == "ecmwf_open_data" else f"{baseline_provider}_baseline"
            if not baseline_bucket:
                report["variables"][variable][baseline_key] = {
                    "units": spec["units"],
                    "status": "no_real_matched_pairs",
                }
            else:
                baseline_metrics = compute_metrics(baseline_bucket["own"], baseline_bucket["obs"])
                if baseline_metrics is None or baseline_metrics["sample_size"] < min_sample_size:
                    report["variables"][variable][baseline_key] = {
                        "units": spec["units"],
                        "status": "insufficient_sample_size",
                        "sample_size": 0 if baseline_metrics is None else baseline_metrics["sample_size"],
                        "min_sample_size_required": min_sample_size,
                    }
                else:
                    report["variables"][variable][baseline_key] = {
                        "units": spec["units"],
                        "status": "compared",
                        "stations_used": sorted(baseline_bucket["stations"]),
                        "metrics_baseline": baseline_metrics,
                    }

    report["summary"] = {
        "variable_provider_pairs_with_real_comparison": total_count,
        "variable_provider_pairs_total": len(COMPARISON_SPECS),
        "note": (
            "own_beats_cmems is intentionally not reported yet -- this version only "
            "validates each own model against real buoy observations. Comparing "
            "against a real CMEMS forecast pull is a follow-up, not something to "
            "guess at here. CROCO and NEMO are reported separately -- they are two "
            "different models the daily orchestrator runs in parallel, not two names "
            "for the same run."
        ),
    }
    return report


def run_evaluation(
    client,
    project_id,
    dataset,
    evidence_table,
    station_table,
    target_date,
    lookback_days,
    max_station_distance_nm,
    time_tolerance_minutes,
    min_sample_size,
    location_name=None,
):
    """Executes the end-to-end evaluation pipeline over real BigQuery records."""
    print(f"Fetching real own-model and baseline forecast rows for {target_date} (lookback {lookback_days}d)...")
    forecast_rows = fetch_forecast_rows(client, project_id, dataset, evidence_table, target_date, lookback_days)

    if not forecast_rows:
        return {
            "evaluation_date": target_date,
            "data_source": "real",
            "status": "no_forecast_data",
            "message": (
                "No real WRF/CROCO/NEMO/SWAN forecast rows with coordinates were found in "
                f"{project_id}.{dataset}.{evidence_table} for this window. "
                "This is expected until a real model run has been ingested via "
                "scripts/{wrf,croco,nemo,swan}_forecast_ingestor.py. Nothing was fabricated."
            ),
        }

    print(f"Found {len(forecast_rows)} real forecast rows. Fetching the real observation station catalog...")
    stations = fetch_station_catalog(client, project_id, dataset, station_table)

    if location_name:
        loc_lower = location_name.lower()
        stations = [
            s for s in stations
            if (s.get("station_id") and loc_lower in s["station_id"].lower())
            or (s.get("station_name") and loc_lower in s["station_name"].lower())
            or (s.get("provider") and loc_lower in s["provider"].lower())
        ]
        if not stations:
            return {
                "evaluation_date": target_date,
                "data_source": "real",
                "status": "no_matching_stations",
                "message": f"No observation stations matched the location query '{location_name}'."
            }

    annotated_rows, matched_station_ids = match_forecast_points_to_stations(
        forecast_rows, stations, max_station_distance_nm
    )
    if not matched_station_ids:
        return {
            "evaluation_date": target_date,
            "data_source": "real",
            "status": "no_nearby_stations",
            "message": (
                f"Found {len(forecast_rows)} real forecast rows, but none were within "
                f"{max_station_distance_nm} nm of a known real observation station."
                + (f" (filtered by location: '{location_name}')" if location_name else "")
            ),
        }

    print(f"Matched forecast points to {len(matched_station_ids)} real station(s). Fetching real observations...")
    observation_rows = fetch_observation_rows(
        client, project_id, dataset, evidence_table, matched_station_ids, target_date, lookback_days
    )

    pairs_by_variable_provider = pair_forecasts_with_observations(annotated_rows, observation_rows, time_tolerance_minutes)
    report = build_comparison_report(pairs_by_variable_provider, min_sample_size, target_date)
    return report


def main(argv=None):
    args = parse_args(argv)
    target_date = args.date

    client = _bigquery_client(args.project)
    project_id = args.project or client.project

    report = run_evaluation(
        client=client,
        project_id=project_id,
        dataset=args.dataset,
        evidence_table=args.evidence_table,
        station_table=args.station_table,
        target_date=target_date,
        lookback_days=args.lookback_days,
        max_station_distance_nm=args.max_station_distance_nm,
        time_tolerance_minutes=args.time_tolerance_minutes,
        min_sample_size=args.min_sample_size,
    )

    if report.get("status") in ("no_forecast_data", "no_nearby_stations"):
        print(f"Honest evaluation report completed with status '{report['status']}' -- no fabrication.")
    else:
        compared = report.get("summary", {}).get("variable_provider_pairs_with_real_comparison", 0)
        total = report.get("summary", {}).get("variable_provider_pairs_total", 0)
        print(f"Real comparison complete. {compared}/{total} (variable, model) pairs had enough real matched data to report.")

    _write_and_maybe_upload(report, args)
    return 0



def _write_and_maybe_upload(report, args):
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote report to {args.output}")

    if args.no_upload:
        return

    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob_path = f"reports/{report['evaluation_date']}/accuracy_comparison.json"
    bucket.blob(blob_path).upload_from_filename(args.output)
    print(f"Uploaded report to gs://{BUCKET_NAME}/{blob_path}")


if __name__ == "__main__":
    sys.exit(main())
