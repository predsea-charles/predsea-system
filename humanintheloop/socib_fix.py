import os
import requests
from dotenv import load_dotenv

# 1. Load and Clean
load_dotenv()
raw_key = os.getenv("SOCIB_API_KEY")

if not raw_key:
    print("CRITICAL: No SOCIB_API_KEY found in .env")
    exit()

# Clean key of any accidental quotes or whitespace
api_key = raw_key.strip().replace('"', '').replace("'", "")

print(f"Diagnostic: Key found starting with '{api_key[:4]}...' (Length: {len(api_key)})")

# 2. Test Connection with the specific SOCIB Header format
def test_connection():
    # Target the Dragonera Buoy
    url = "https://api.socib.es/instruments/143/data/latest/"

    # SOCIB strictly requires 'Token <key>'
    headers = {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json"
    }

    print(f"Requesting: {url}")
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        print("✅ SUCCESS: Connection established.")
        data = response.json()
        print(f"Latest Wave Height at Dragonera: {data.get('WHT_MSIG')}m")
    elif response.status_code == 401:
        print("❌ FAILED: 401 Unauthorized. The key is being rejected by SOCIB.")
        print("Action: Log in to apps.socib.es and double-check the API Key in your User Profile.")
    else:
        print(f"❌ FAILED: Status Code {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    test_connection()
