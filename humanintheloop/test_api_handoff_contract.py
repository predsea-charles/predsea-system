import json
from pathlib import Path
from api.app import app

def test_openapi_file_exists_and_is_valid_json():
    json_path = Path("/Users/charles.santana/PredSea/predsea-system/docs/api/openapi.json")
    assert json_path.is_file(), "openapi.json does not exist!"
    
    with open(json_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
        
    assert "paths" in schema, "OpenAPI schema must contain paths!"
    assert len(schema["paths"]) > 0, "OpenAPI schema has zero paths!"

def test_openapi_schema_matches_live_routing():
    # Build openapi from live app
    live_schema = app.openapi()
    
    json_path = Path("/Users/charles.santana/PredSea/predsea-system/docs/api/openapi.json")
    with open(json_path, "r", encoding="utf-8") as f:
        stored_schema = json.load(f)
        
    # Standard comparisons
    assert live_schema["info"]["title"] == stored_schema["info"]["title"]
    
    live_paths = set(live_schema["paths"].keys())
    stored_paths = set(stored_schema["paths"].keys())
    
    # Stored schema must cover all live endpoints (drift checking)
    difference = live_paths.symmetric_difference(stored_paths)
    assert len(difference) == 0, f"Drift detected in routes! Symmetric difference: {difference}"

def test_essential_endpoints_present_in_app():
    routes = [r.path for r in app.routes]
    
    # We require these core endpoints to exist for frontend remapping
    required_patterns = [
        "/health",
        "/places",
        "/routes",
        "/places/resolve",
        "/places/{place_id}/weather"
    ]
    
    for pattern in required_patterns:
        assert any(pattern in r for r in routes), f"Essential route pattern {pattern} not registered in app!"
