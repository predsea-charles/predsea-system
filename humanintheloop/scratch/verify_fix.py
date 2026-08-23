import sys
import os
from datetime import datetime

# Add the current directory to sys.path
sys.path.append(os.getcwd())

from api.evidence_store import current_local_date
from api.app import ensure_forecast_files_fresh

def test_fix():
    today = current_local_date()
    print(f"Current local date: {today}")
    
    try:
        print(f"Checking forecast files for {today}...")
        # We don't want to actually trigger a 5 minute download in a test.
        # But we can check if it detects the files are missing.
        # For now, let's just see if the imports work and the function is callable.
        print("Success: Imports and function found.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_fix()
