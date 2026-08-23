# PredSea Place Resolution and Distance Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PredSea the single source of truth for place resolution and maritime distance calculations, with canonical Balearic place data, aliases, and mixed place/coordinate distance support.

**Architecture:** Move place identity into PredSea-managed seed and alias JSON files, load them inside the existing place registry, and expose a new resolver endpoint plus a mixed distance endpoint that can combine place IDs and coordinates. Keep the existing fixed place-pair table and maritime route fallback intact, but route all new place lookups through the PredSea catalog instead of any relay-side or duplicated place database.

**Tech Stack:** Python, FastAPI, Pydantic, JSON seed files, existing `searoute` fallback, pytest.

---

### Task 1: Add the PredSea-managed place seed and alias files

**Files:**
- Create: `places_seed_balearics.json`
- Create: `aliases_balearics.json`
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_place_resolution_uses_predsea_aliases(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/places/resolve?query=portals")

    assert response.status_code == 200
    payload = response.json()
    assert payload["matched"] is True
    assert payload["place_id"] == "porto_portals"
    assert payload["place_name"] == "Puerto Portals"
    assert payload["type"] == "port"
    assert payload["confidence"] == "high"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k place_resolution_uses_predsea_aliases -v`
Expected: FAIL because the seed and alias files are not loaded yet and `/places/resolve` does not exist.

- [ ] **Step 3: Add the seed and alias files**

Create `places_seed_balearics.json` with the current canonical place records plus the new Balearic coverage we want to resolve. Keep the IDs stable for existing places such as `palma`, `ibiza`, `formentera`, `menorca`, `cabrera`, `ciutadella`, `alcudia`, `soller`, `barcelona`, `valencia`, and `portocolom`. Include new entries for the explicit ports and areas we want to resolve, such as `porto_portals`, `west_ibiza`, and `mahon`.

Create `aliases_balearics.json` with alias-to-place mappings like:

```json
{
  "palma": "palma",
  "port palma": "palma",
  "ibiza": "ibiza",
  "eivissa": "ibiza",
  "formentera": "formentera",
  "portals": "porto_portals",
  "mao": "mahon"
}
```

- [ ] **Step 4: Run the test to verify it still fails for the endpoint**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k place_resolution_uses_predsea_aliases -v`
Expected: still FAIL until the resolver endpoint is added.

- [ ] **Step 5: Commit**

```bash
git add places_seed_balearics.json aliases_balearics.json test_api_app.py
git commit -m "Add PredSea place seed and alias files"
```

### Task 2: Load the new place catalog inside PredSea

**Files:**
- Modify: `place_registry.py`
- Modify: `api/app.py`
- Modify: `api/schemas.py`
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_place_resolution_returns_catalog_entry(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/places/resolve?query=eivissa")

    assert response.status_code == 200
    payload = response.json()
    assert payload["matched"] is True
    assert payload["place_id"] == "ibiza"
    assert payload["place_name"] == "Ibiza"
    assert payload["type"] == "main_place"
    assert payload["latitude"] == 38.92
    assert payload["longitude"] == 1.49
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k place_resolution_returns_catalog_entry -v`
Expected: FAIL because the loader and endpoint do not exist yet.

- [ ] **Step 3: Implement the catalog loader**

Update `place_registry.py` so the place catalog is sourced from the seed and alias JSON files in `humanintheloop/`. The loader should:

```python
def load_place_catalog() -> dict[str, dict]:
    ...

def load_place_aliases() -> dict[str, str]:
    ...
```

Keep the existing canonical place IDs and metadata shape, but make the JSON files the source of truth. Preserve the existing distance resolver and `searoute` fallback behavior.

- [ ] **Step 4: Add the resolver endpoint**

Add `GET /places/resolve?query=...` in `api/app.py`. The response should include:

```python
{
    "query": "eivissa",
    "matched": True,
    "place_id": "ibiza",
    "place_name": "Ibiza",
    "type": "main_place",
    "latitude": 38.92,
    "longitude": 1.49,
    "confidence": "high"
}
```

If the query cannot be matched, return `matched: false`, `confidence: "low"`, and null place fields rather than inventing a result.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k 'place_resolution_uses_predsea_aliases or place_resolution_returns_catalog_entry' -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add place_registry.py api/app.py api/schemas.py test_api_app.py
git commit -m "Load PredSea place catalog and add resolver endpoint"
```

### Task 3: Add the mixed distance endpoint

**Files:**
- Modify: `api/app.py`
- Modify: `api/schemas.py`
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_places_distance_mixed_supports_place_to_coordinates(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get(
        "/places/distance/mixed?origin=palma&destination_latitude=38.92&destination_longitude=1.49"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin"]["place_id"] == "palma"
    assert payload["destination"]["coordinates"]["latitude"] == 38.92
    assert payload["method"] in ("place_to_coordinates", "mixed_maritime_route")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k places_distance_mixed_supports_place_to_coordinates -v`
Expected: FAIL because the endpoint does not exist yet.

- [ ] **Step 3: Implement the mixed distance endpoint**

Add `GET /places/distance/mixed` with support for:

- place → place
- coordinates → coordinates
- coordinates → place
- place → coordinates

Use PredSea’s existing place resolver first, then use the maritime sea-route distance logic. Keep the response shape explicit about what was resolved on each side so callers can see whether a place ID or coordinates were used.

Suggested response shape:

```python
{
    "method": "place_to_coordinates",
    "origin": {...},
    "destination": {...},
    "distance_nm": 67.9,
    "estimated_time_h": 4.53,
    "source_tag": "graph_sea_route_v1"
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k places_distance_mixed_supports_place_to_coordinates -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add api/app.py api/schemas.py test_api_app.py
git commit -m "Add mixed distance endpoint"
```

### Task 4: Update documentation and verify the API contract

**Files:**
- Modify: `api/README.md`
- Modify: `docs/api-whatsapp.md`
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing documentation expectation test**

```python
def test_places_resolve_endpoint_is_documented():
    from pathlib import Path
    readme = Path("api/README.md").read_text()
    assert "/places/resolve" in readme
    assert "/places/distance/mixed" in readme
```

- [ ] **Step 2: Update the docs**

Document the following clearly:

- PredSea owns the place database.
- `places_seed_balearics.json` and `aliases_balearics.json` are the source of truth.
- `/places/resolve` resolves place names against the PredSea catalog.
- `/places/distance` remains the place-to-place distance endpoint.
- `/places/distance/coordinates` uses maritime sea-route logic for raw coordinates.
- `/places/distance/mixed` supports combinations of place IDs and coordinates.

- [ ] **Step 3: Run the tests**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k places_resolve_endpoint_is_documented -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add api/README.md docs/api-whatsapp.md test_api_app.py
git commit -m "Document PredSea place resolution architecture"
```

### Self-check before merge

- Confirm the old hardcoded place list is gone or only used as a thin compatibility layer.
- Confirm Relay/WhatsAuction/Kobe are not carrying any place database logic.
- Confirm all new endpoints resolve through PredSea only.
- Confirm the place distance and route distance behaviors stay distinct and predictable.
