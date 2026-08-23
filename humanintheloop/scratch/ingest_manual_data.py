import os
import json
import datetime
from pathlib import Path
from datetime import timezone
import sys

# Add humanintheloop to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import place_weather
import ingest_observations
import fetch_data
import fetch_ecmwf

def ingest_manual_data():
    dates = [
        "2026-07-12",
        "2026-07-13",
        "2026-07-14",
        "2026-07-15",
        "2026-07-16",
        "2026-07-17"
    ]
    run_id = "manual_recovery"
    
    project_root = Path(__file__).resolve().parents[2]
    predictions_root = project_root / "predictions"
    
    mvp_data_dir = Path(__file__).resolve().parent.parent / "mvp_data"
    waves_path = mvp_data_dir / "balearic_waves.nc"
    currents_path = mvp_data_dir / "balearic_currents.nc"
    
    wind_path = mvp_data_dir / "ecmwf_wind.nc"
    if not wind_path.exists():
        print("Fetching atmospheric wind data (ECMWF Tier 3)...")
        wind_result = fetch_ecmwf.fetch_ecmwf_wind(output_dir=str(mvp_data_dir))
        wind_path = Path(wind_result.get("dataset_path")) if isinstance(wind_result, dict) and wind_result.get("available") else None
    
    print(f"Wind data available: {wind_path}")
    
    for run_date in dates:
        print(f"\nProcessing date: {run_date}")
        run_dir = predictions_root / run_date / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"Skipping observations for speed...")
        observations = {}
        
        # Prioritize requested place and some key ones
        priority_places = ["ventotene_porto_vecchio_harbour_33fcdef", "palma", "ibiza", "barcelona", "valencia"]
        all_available = place_weather.available_place_ids()
        
        # Process only priority places and a small subset for now
        places_to_process = priority_places + [p for p in all_available if p not in priority_places][:20]

        print(f"Generating weather packages for {len(places_to_process)} places in {run_dir}...")
        place_weather.write_place_weather_outputs(
            run_dir=run_dir,
            run_date=run_date,
            run_id=run_id,
            waves_path=str(waves_path),
            currents_path=str(currents_path),
            wind_path=str(wind_path) if wind_path else None,
            observations=observations,
            place_ids=places_to_process
        )
        
        # Create latest_run.json
        latest_run_path = predictions_root / run_date / "latest_run.json"
        latest_run_path.parent.mkdir(parents=True, exist_ok=True)
        with open(latest_run_path, "w", encoding="utf-8") as f:
            json.dump({"run_id": run_id, "created_at_utc": datetime.datetime.now(timezone.utc).isoformat()}, f, indent=2)
        
        print(f"Successfully ingested manual data into {run_dir}")
        print(f"Updated {latest_run_path}")

if __name__ == "__main__":
    ingest_manual_data()
