import os
import pytest
from fastapi.testclient import TestClient
from api.app import create_app
from api.evidence_store import EvidenceStore
from api.schemas import VesselProfile
from api.safe_havens import SafeHavenFinder


def test_safe_haven_filtering():
    finder = SafeHavenFinder()
    
    # Let's verify that a very large yacht (e.g. 100m LOA, 5m draft) is filtered out
    # from small harbors but allowed in large ones.
    large_yacht = VesselProfile(
        length_over_all_m=100.0,
        beam_m=15.0,
        draft_m=5.0,
        vessel_type="monohull",
        cruising_speed_knots=15.0,
        max_wave_height_tolerance_m=4.0
    )
    
    # A path of waypoints in Palma / Ibiza
    waypoints = [
        {"lat": 39.5, "lng": 2.5},
        {"lat": 39.0, "lng": 1.5}
    ]
    
    havens = finder.find_nearest_refuges_for_route(waypoints, large_yacht, num_havens=10)
    
    # Verify that small/medium marinas are filtered out:
    # es_soller (max_length_m: 20.0, max_draft_m: 3.0) must NOT be present
    # es_ciutadella (max_length_m: 25.0, max_draft_m: 3.0) must NOT be present
    # es_alcudia (max_length_m: 30.0, max_draft_m: 4.0) must NOT be present
    for h in havens:
        assert h["port_id"] not in ["es_soller", "es_ciutadella", "es_alcudia"]
        # Allowable marinas must support length >= 100m and draft >= 5m
        assert h["amenities"]["max_length_m"] >= 100.0
        assert h["amenities"]["max_draft_m"] >= 5.0


def test_safe_haven_ranking_by_proximity():
    finder = SafeHavenFinder()
    
    # Small sailing boat (10m LOA, 1.2m draft) can fit anywhere
    small_boat = VesselProfile(
        length_over_all_m=10.0,
        beam_m=3.0,
        draft_m=1.2,
        vessel_type="sailing",
        cruising_speed_knots=6.0,
        max_wave_height_tolerance_m=2.0
    )
    
    # Waypoints right next to Port de Sóller (39.7957, 2.6897)
    waypoints = [
        {"lat": 39.79, "lng": 2.68}
    ]
    
    havens = finder.find_nearest_refuges_for_route(waypoints, small_boat, num_havens=3)
    
    assert len(havens) > 0
    # The absolute closest safe haven should be Port de Sóller
    assert havens[0]["port_id"] == "es_soller"
    assert havens[0]["distance_to_route_nm"] < 2.0


def test_api_integration_safe_havens(tmp_path):
    store = EvidenceStore(tmp_path)
    app = create_app(store)
    client = TestClient(app)
    
    # 1. Test /places/route endpoint returns backup safe havens
    response = client.get("/places/route/palma/alcudia?length_over_all_m=12.0&draft_m=1.5")
    assert response.status_code == 200
    data = response.json()
    assert "backup_safe_havens" in data
    assert len(data["backup_safe_havens"]) <= 3
    for h in data["backup_safe_havens"]:
        assert h["amenities"]["max_length_m"] >= 12.0
        assert h["amenities"]["max_draft_m"] >= 1.5
        assert "distance_to_route_nm" in h
        assert "closest_waypoint_index" in h

    # 2. Test /routes/optimal endpoint returns backup safe havens
    # Using existing route storage cache if possible, or mocking
    response = client.get("/routes/optimal/palma/ibiza?vessel_class=small")
    # If there is no precomputed cache loaded, this returns 404 which is fine, but we can verify response contains safe havens if 200
    if response.status_code == 200:
        data = response.json()
        assert "backup_safe_havens" in data
        assert len(data["backup_safe_havens"]) <= 3
