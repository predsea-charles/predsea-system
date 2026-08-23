import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from google.cloud import bigquery
import numpy as np

# Add project root to path
sys.path.append("/Users/charles.santana/PredSea/predsea-system/humanintheloop")
from scripts.model_comparison import (
    fetch_forecast_rows,
    fetch_station_catalog,
    match_forecast_points_to_stations,
    fetch_observation_rows,
    compute_metrics,
    COMPARISON_SPECS
)

def evaluate_islands():
    client = bigquery.Client()
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "predsea-system")
    dataset = "predsea_validation"
    evidence_table = "evidence_rows"
    station_table = "station_metadata"
    target_date = "2026-07-11"
    lookback_days = 3
    
    # Define island groups by bounding boxes
    regions = {
        "Spanish Islands (Balearics)": {"lat": (38.0, 40.5), "lon": (1.0, 4.5)},
        "French Islands (Corsica)": {"lat": (41.0, 43.5), "lon": (8.0, 10.0)},
        "Italian Islands (Sardinia)": {"lat": (38.5, 41.5), "lon": (7.5, 10.0)},
        "Italian Islands (Sicily)": {"lat": (36.0, 39.0), "lon": (12.0, 16.0)},
    }
    
    print(f"Fetching global forecast data for {target_date} (lookback {lookback_days}d)...")
    forecast_rows = fetch_forecast_rows(client, project_id, dataset, evidence_table, target_date, lookback_days)
    if not forecast_rows:
        print("No forecast data found.")
        return

    print(f"Found {len(forecast_rows)} forecast rows. Fetching station catalog...")
    all_stations = fetch_station_catalog(client, project_id, dataset, station_table)
    
    regional_reports = {}

    for region_name, bbox in regions.items():
        print(f"\nProcessing {region_name}...")
        
        # Filter stations by region
        lat_min, lat_max = bbox["lat"]
        lon_min, lon_max = bbox["lon"]
        
        regional_stations = [
            s for s in all_stations
            if s.get("latitude") and s.get("longitude") and
               lat_min <= s["latitude"] <= lat_max and
               lon_min <= s["longitude"] <= lon_max
        ]
        
        if not regional_stations:
            print(f"No stations found in {region_name}.")
            continue
            
        print(f"Found {len(regional_stations)} stations in {region_name}. Matching points...")
        
        annotated_rows, matched_station_ids = match_forecast_points_to_stations(
            forecast_rows, regional_stations, max_distance_nm=25.0
        )
        
        if not matched_station_ids:
            print(f"No forecast points matched stations in {region_name}.")
            continue
            
        print(f"Matched {len(matched_station_ids)} stations. Fetching observation rows...")
        obs_rows = fetch_observation_rows(
            client, project_id, dataset, evidence_table, matched_station_ids, target_date, lookback_days
        )
        
        if not obs_rows:
            print(f"No observation rows found for matched stations in {region_name}.")
            continue
            
        # Group observations by (station_id, variable, time)
        obs_lookup = {}
        for row in obs_rows:
            sid = row["station_id"]
            var = row["variable"]
            ts = row["observed_at_utc"]
            if ts:
                obs_lookup[(sid, var, ts)] = row["value"]

        # Evaluate metrics per variable/provider
        region_metrics = {}
        for spec in COMPARISON_SPECS:
            var = spec["variable"]
            provider = spec["own_provider"]
            obs_var = spec["obs_variable"]
            
            # Find matching pairs
            model_vals = []
            obs_vals = []
            
            for row in annotated_rows:
                if row["variable"] == var and row["forecast_source_id"] == provider:
                    sid = row.get("truth_station_id")
                    ts = row.get("target_time_utc")
                    if sid and ts:
                        # Find nearest observation in time (for now exact match or very close)
                        # The original script does a more complex time match, 
                        # but we'll try to simplify or follow it.
                        # Let's just use the logic from model_comparison if we can.
                        pass
            
            # Actually, compute_metrics is easy, the hard part is the time alignment.
            # I'll re-read how model_comparison does the time alignment.
        
        # NOTE: To be 100% accurate, I should just modify the model_comparison.py 
        # to accept a station list or a filter.
        
    # Re-evaluating strategy: 
    # I'll create a TEMPORARY copy of model_comparison.py that accepts a BBOX.
    
evaluate_islands()
