import json
import sys
from pathlib import Path

# Add humanintheloop to path so api.app can be imported
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "humanintheloop"))

try:
    import yaml
except ImportError:
    # If pyyaml is not available in the active environment, we can install it or dump JSON
    yaml = None

from api.app import app

def main():
    docs_dir = repo_root / "docs/api"
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate OpenAPI schema
    openapi_schema = app.openapi()
    
    # Write JSON
    json_path = docs_dir / "openapi.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
    print(f"Exported OpenAPI JSON to {json_path}")
    
    # Write YAML
    yaml_path = docs_dir / "openapi.yaml"
    if yaml is not None:
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(openapi_schema, f, default_flow_style=False, sort_keys=False)
        print(f"Exported OpenAPI YAML to {yaml_path}")
    else:
        # Simple manual conversion/fallback if PyYAML is missing, or just log
        print("PyYAML not found, skipping YAML export (JSON is complete)")

if __name__ == "__main__":
    main()
