import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("SOCIB_API_KEY")

# This is the "Data Services" URL often used in SOCIB notebooks
BASE_URL = "https://api.socib.es/data-sources/"
TARGET_PLATFORMS = {
    "Station_Pollensa": "Pollença station",
    "Buoy_CanalDeIbiza": "Canal de Ibiza buoy",
    "HF_Radar_Ibiza": "Ibiza Channel HF radar",
}


def clean_api_key(raw_key):
    if not raw_key:
        return None
    return raw_key.strip().replace('"', "").replace("'", "")


def build_headers(api_key):
    # SOCIB's API rejects Authorization: Token and application/json here.
    return {"apikey": api_key}


def platform_id(source):
    platform_url = source.get("platform") or ""
    return platform_url.rstrip("/").split("/")[-1]

def get_balearic_status():
    api_key = clean_api_key(API_KEY)
    if not api_key:
        print("CRITICAL: No SOCIB_API_KEY found in .env")
        return

    # Filters based on the SOCIB GitHub examples
    params = {
        "is_active": "true",
        "has_data": "true",
        "processing_level": "L2",  # Quality controlled data
        "page_size": 100,
    }

    print("Requesting latest Balearic data sources...")
    response = requests.get(BASE_URL, headers=build_headers(api_key), params=params, timeout=30)

    if response.status_code == 200:
        data = response.json()
        results = data.get('results', [])

        # We look for your specific needs: Waves, Temp, Currents
        found = False
        for source in results:
            platform = platform_id(source)
            if platform in TARGET_PLATFORMS:
                found = True
                print(f"Found Source: {TARGET_PLATFORMS[platform]}")
                print(f"  > Platform: {platform}")
                print(f"  > ID: {source.get('id')}")
                print(f"  > Instrument Type: {source.get('instrument_type')}")
                print(f"  > Last Update: {source.get('end_datetime')}")
        if not found:
            print("No matching Balearic sources found on the first API page.")
    else:
        print(f"Failed with {response.status_code}")
        print(response.text[:500])
        print("Tip: SOCIB expects the API key in the 'apikey' header for this endpoint.")

if __name__ == "__main__":
    get_balearic_status()
