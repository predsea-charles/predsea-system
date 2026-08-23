import os
import pytest
import datetime
from pygeomag import GeoMag
from fastapi.testclient import TestClient
from api.app import create_app, enrich_route_elements_with_headings
from api.evidence_store import EvidenceStore


def test_wmm_mallorca():
    geo_mag = GeoMag()
    dt = datetime.datetime(2026, 6, 29)
    # Calculate decimal year
    year_start = datetime.datetime(dt.year, 1, 1)
    year_end = datetime.datetime(dt.year + 1, 1, 1)
    decimal_year = dt.year + (dt - year_start) / (year_end - year_start)
    
    result = geo_mag.calculate(39.5, 2.5, 0, decimal_year)
    # result.d is declination (magnetic variation) in degrees.
    # Mallorca variation is easterly, around 1.9 degrees in 2026.
    assert 1.0 < result.d < 3.0


def test_api_magnetic_variation(tmp_path):
    store = EvidenceStore(tmp_path)
    app = create_app(store)
    client = TestClient(app)
    
    response = client.get("/navigation/magnetic-variation?latitude=39.5&longitude=2.5&date=2026-06-29")
    assert response.status_code == 200
    data = response.json()
    assert data["latitude"] == 39.5
    assert data["longitude"] == 2.5
    assert "magnetic_variation_deg" in data
    assert 1.0 < data["magnetic_variation_deg"] < 3.0


def test_enrich_route_elements_with_headings():
    waypoints = [
        {"lat": 39.5, "lng": 2.5},
        {"lat": 39.0, "lng": 2.0}
    ]
    enriched = enrich_route_elements_with_headings(waypoints, "2026-06-29")
    assert len(enriched) == 2
    assert "true_heading_deg" in enriched[0]
    assert "magnetic_variation_deg" in enriched[0]
    assert "magnetic_heading_deg" in enriched[0]
    
    # Check that headings for the last waypoint are copied from the previous one
    assert enriched[1]["true_heading_deg"] == enriched[0]["true_heading_deg"]
    assert enriched[1]["magnetic_variation_deg"] == enriched[0]["magnetic_variation_deg"]
    assert enriched[1]["magnetic_heading_deg"] == enriched[0]["magnetic_heading_deg"]
