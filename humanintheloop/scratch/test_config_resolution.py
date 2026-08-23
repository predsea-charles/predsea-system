import os
import sys
from pathlib import Path

# Add humanintheloop to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import bigquery_export

def test_resolve_config():
    print("Testing resolve_config...")
    # Clear env vars that might interfere
    os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    os.environ.pop("PREDSEA_BIGQUERY_PROJECT", None)
    os.environ.pop("PREDSEA_BIGQUERY_DATASET", None)
    os.environ.pop("PREDSEA_ENV", None)
    
    config = bigquery_export.resolve_config()
    print(f"Config with no env vars: {config}")
    
    os.environ["PREDSEA_ENV"] = "prod"
    config_prod = bigquery_export.resolve_config()
    print(f"Config with PREDSEA_ENV=prod: {config_prod}")
    
    # Test project detection
    try:
        import google.auth
        _, project = google.auth.default()
        print(f"Detected project from auth: {project}")
    except Exception as e:
        print(f"Could not detect project from auth: {e}")

if __name__ == "__main__":
    test_resolve_config()
