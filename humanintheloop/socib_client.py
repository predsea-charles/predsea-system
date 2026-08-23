import os
import requests
import pandas as pd
from dotenv import load_dotenv

# Load credentials
load_dotenv()
API_KEY = os.getenv("SOCIB_API_KEY")
HEADERS = {"Authorization": f"Token {API_KEY}"}

# Constant IDs for the Balearic MVP (Verified from SOCIB catalog)
# Dragonera is the "gatekeeper" for the Mallorca-Ibiza channel
STATIONS = {
    "dragonera": "143", # Mooring: Waves, Temp, Salinity
    "pollença": "144",  # Mooring: Waves, Temp
    "ibiza_channel": "72" # Radar: Surface Velocity/Streams
}

def get_latest_obs(instrument_id):
    """Fetches latest real-time data from a specific SOCIB instrument."""
    url = f"https://api.socib.es/instruments/{instrument_id}/data/latest/"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching station {instrument_id}: {e}")
        return None

def format_briefing():
    """Compiles the metrics into a clear format for your WhatsApp briefing."""
    print("--- PREDSEA LOCAL INTELLIGENCE ---")

    # 1. Wave and Temp Data (Dragonera)
    drag_data = get_latest_obs(STATIONS["dragonera"])
    if drag_data:
        # Note: variable names in SOCIB JSON can vary (e.g., WHT_MSIG or WHT_HMAX)
        wave_height = drag_data.get('WHT_MSIG', 'N/A')
        water_temp = drag_data.get('WTMP', 'N/A')
        print(f"Station: Dragonera (Channel Entrance)")
        print(f"  > Wave Height: {wave_height} m")
        print(f"  > Water Temp: {water_temp} °C")

    # 2. Stream/Current Velocity (Radar)
    radar_data = get_latest_obs(STATIONS["ibiza_channel"])
    if radar_data:
        # Radar returns vectors (u, v)
        u = radar_data.get('cur_u', 0)
        v = radar_data.get('cur_v', 0)
        velocity = (u**2 + v**2)**0.5 # Calculate total speed
        print(f"Station: Ibiza Channel (HF-Radar)")
        print(f"  > Current Speed: {velocity:.2f} m/s")

if __name__ == "__main__":
    format_briefing()
