import os
import sys
from pathlib import Path

# Add workspace root to python path
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

import socib_api

# Use the API key from .env (which will be loaded automatically if we call build_headers or let socib_api do it)
api_key = os.getenv("SOCIB_API_KEY")
print(f"Using SOCIB API Key: {api_key}")

# Let's fetch weather stations and oceanographic buoys
platforms = []
for ptype in ["Oceanographic Buoy", "Weather Station"]:
    print(f"Fetching platforms of type '{ptype}'...")
    try:
        discovered = socib_api.fetch_platforms(platform_type=ptype, api_key=api_key)
        print(f"Found {len(discovered)} platforms.")
        platforms.extend(discovered)
    except Exception as e:
        print(f"Error: {e}")

print(f"Total discovered platforms: {len(platforms)}")
print("\nSearching for platforms with wind or weather sensors...")
for p in platforms:
    pid = p.get("id")
    pname = p.get("name")
    try:
        sources = socib_api.fetch_data_sources(platform_id=pid, api_key=api_key)
        for s in sources:
            s_id = s.get("id")
            s_name = s.get("name")
            instrument = s.get("instrument_type", "")
            # Let's fetch latest data to see columns
            try:
                latest = socib_api.fetch_latest_data(s_id, api_key=api_key)
                results = socib_api.unwrap_results(latest)
                if results:
                    first = results[0]
                    # Check if wind_speed or similar exists in columns
                    wind_keys = [k for k in first.keys() if "wind" in k.lower() or k in ("U10", "U", "V", "WSPD", "WDIR")]
                    if wind_keys:
                        print(f"Platform: {pname} (ID: {pid}) | Source: {s_name} (ID: {s_id}) | Instrument: {instrument}")
                        print(f"  > Latest sample keys: {list(first.keys())}")
                        print(f"  > Wind keys: {wind_keys}")
                        print(f"  > Sample time: {first.get('time') or first.get('timestamp')}")
            except Exception as ex:
                pass
    except Exception as e:
        print(f"Error fetching sources for {pname}: {e}")
