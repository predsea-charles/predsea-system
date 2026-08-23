import os
import sys
from pathlib import Path

# Add workspace root to python path
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

import socib_api

api_key = os.getenv("SOCIB_API_KEY")
print(f"Using SOCIB API Key: {api_key}")

# Specific platform IDs we are interested in
target_platform_ids = ["Station_Pollensa", "Buoy_CanalDeIbiza", "Buoy_BahiaDePalma", "Buoy_PortoColom"]

print("Fetching data sources for target platforms...")
for pid in target_platform_ids:
    print(f"\nPlatform: {pid}")
    try:
        sources = socib_api.fetch_data_sources(platform_id=pid, api_key=api_key)
        print(f"Found {len(sources)} data sources.")
        for s in sources:
            s_id = s.get("id")
            s_name = s.get("name")
            instrument = s.get("instrument_type", "")
            
            # Fetch latest to see available variables
            try:
                latest = socib_api.fetch_latest_data(s_id, api_key=api_key)
                results = socib_api.unwrap_results(latest)
                if results:
                    first = results[0]
                    wind_keys = [k for k in first.keys() if "wind" in k.lower() or k in ("U10", "U", "V", "WSPD", "WDIR")]
                    print(f"  Source: {s_name} (ID: {s_id}) | Instrument: {instrument}")
                    print(f"    > Variables: {list(first.keys())}")
                    if wind_keys:
                        print(f"    > Wind variables: {wind_keys}")
                        
                        # Let's check if we have data on 2026-04-29
                        for target_date in ["2026-04-29", "2026-06-24"]:
                            try:
                                initial_dt = f"{target_date}T00:00:00Z"
                                end_dt = f"{target_date}T23:59:59Z"
                                print(f"    > Querying historical data for {target_date}...")
                                hist = socib_api.fetch_historical_data(s_id, initial_dt, end_dt, api_key=api_key)
                                hist_rows = socib_api.unwrap_results(hist)
                                print(f"      Got {len(hist_rows)} historical records.")
                                if hist_rows:
                                    print(f"      First record sample: {hist_rows[0]}")
                            except Exception as ex_hist:
                                print(f"      Error querying history: {ex_hist}")
            except Exception as ex:
                print(f"  Error fetching latest for source {s_name} (ID: {s_id}): {ex}")
    except Exception as e:
        print(f"Error fetching sources for platform {pid}: {e}")
