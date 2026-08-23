# Spatial & Route Topology Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the new coastal places and public route topology for the requested island/mainland route mesh without breaking the existing route registry.

**Architecture:** Keep the canonical place registry as the source of truth for new coastal nodes, then extend the route registry with alphabetical route keys so the ETL, API, and public route inventory all pick up the new topology automatically. Preserve all existing routes exactly as they are and only add new records and route exposure notes on top.

**Tech Stack:** JSON place/route seed files, Python registry loading, route analysis tests, API route inventory docs.

---

### Task 1: Register new coastal places in the canonical place seeds

**Files:**
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/places_seed_balearics.json`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/aliases_balearics.json`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/data/places/places_seed_balearics.json`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/data/places/aliases.json`
- Test: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_place_weather.py`

- [ ] **Step 1: Add the failing registry expectations**

```python
def test_available_place_ids_includes_new_coastal_nodes():
    import place_registry
    place_ids = set(place_registry.available_place_ids())
    assert {"san_antonio", "andratx", "fornells", "addaia", "tarragona", "palamos"}.issubset(place_ids)
```

- [ ] **Step 2: Update the seed JSON records**

```json
{
  "id": "san_antonio",
  "name": "Sant Antoni de Portmany",
  "type": "port",
  "latitude": 38.981,
  "longitude": 1.303,
  "parent_place_id": "ibiza",
  "children": [],
  "aliases": ["san antonio", "sant antoni", "sant antoni de portmany"],
  "observation_candidates": ["canal_de_ibiza", "puertos_ibiza", "ibiza"]
}
```

```json
{
  "id": "andratx",
  "name": "Port d'Andratx",
  "type": "port",
  "latitude": 39.544,
  "longitude": 2.385,
  "parent_place_id": "palma",
  "children": [],
  "aliases": ["andratx", "port d'andratx", "port andratx"],
  "observation_candidates": ["bahia_de_palma", "puertos_mallorca", "mallorca", "palma"]
}
```

```json
{
  "id": "fornells",
  "name": "Cala Fornells",
  "type": "anchorage",
  "latitude": 39.937,
  "longitude": 4.131,
  "parent_place_id": "menorca",
  "children": [],
  "aliases": ["fornells", "cala fornells"],
  "observation_candidates": ["mahon", "puertos_mahon", "menorca"]
}
```

```json
{
  "id": "addaia",
  "name": "Port d'Addaia",
  "type": "port",
  "latitude": 39.991,
  "longitude": 4.201,
  "parent_place_id": "menorca",
  "children": [],
  "aliases": ["addaia", "port d'addaia"],
  "observation_candidates": ["mahon", "puertos_mahon", "menorca"]
}
```

```json
{
  "id": "tarragona",
  "name": "Tarragona",
  "type": "main_place",
  "latitude": 41.105,
  "longitude": 1.250,
  "parent_place_id": null,
  "children": [],
  "aliases": ["tarragona"],
  "observation_candidates": ["barcelona", "puertos_barcelona", "valencia", "puertos_valencia"]
}
```

```json
{
  "id": "palamos",
  "name": "Palamos",
  "type": "main_port",
  "latitude": 41.847,
  "longitude": 3.125,
  "parent_place_id": null,
  "children": [],
  "aliases": ["palamos", "palamós"],
  "observation_candidates": ["barcelona", "puertos_barcelona"]
}
```

- [ ] **Step 3: Mirror the new places into the secondary seed files**

```json
{
  "id": "andratx",
  "name": "Port d'Andratx",
  "type": "port",
  "latitude": 39.544,
  "longitude": 2.385,
  "confidence": "high"
}
```

- [ ] **Step 4: Run the place inventory test**

Run:
```bash
./.venv/bin/python -m pytest -q test_place_weather.py::test_available_place_ids_includes_new_coastal_nodes
```
Expected: PASS with the new place IDs present.

### Task 2: Expand the public route topology and route notes

**Files:**
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/routes.json`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/captain_knowledge/route_exposure_notes.yaml`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_socib_scripts.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/api/README.md`

- [ ] **Step 1: Add failing route inventory expectations**

```python
def test_load_routes_includes_route_expansion():
    import route_analysis

    routes = route_analysis.load_routes()
    assert {
    "ciutadella_palma",
    "mahon_palma",
    "formentera_palma",
    "cabrera_ibiza",
    "andratx_ibiza",
    "ibiza_soller",
    "andratx_san_antonio",
    "fornells_mahon",
    "addaia_mahon",
    "fornells_ciutadella",
    "fornells_addaia",
    "alcudia_fornells",
    "tarragona_valencia",
    "barcelona_tarragona",
    "barcelona_palamos",
    "palma_ciutadella",
    "palma_mahon",
  }.issubset(set(routes))
```

- [ ] **Step 2: Add the new route records to `routes.json`**

```json
{
  "id": "ciutadella_palma",
  "name": "Palma -> Ciutadella",
  "origin": { "name": "Palma", "longitude": 2.6502, "latitude": 39.5696 },
  "destination": { "name": "Ciutadella", "longitude": 3.8350, "latitude": 40.0000 }
}
```

```json
{
  "id": "mahon_palma",
  "name": "Palma -> Mahon",
  "origin": { "name": "Palma", "longitude": 2.6502, "latitude": 39.5696 },
  "destination": { "name": "Mahon", "longitude": 4.2660, "latitude": 39.8890 }
}
```

```json
{
  "id": "formentera_palma",
  "name": "Palma -> Formentera",
  "origin": { "name": "Palma", "longitude": 2.6502, "latitude": 39.5696 },
  "destination": { "name": "Formentera", "longitude": 1.4900, "latitude": 38.6800 }
}
```

- [ ] **Step 3: Add the new route exposure notes**

```yaml
ciutadella_palma:
  route: Palma -> Ciutadella
  exposure: Menorca Channel crossing with arrival context near Ciutadella.
  watch_patterns:
    - northerly swell in the channel
    - late-day exposed approach
  default_operational_bias: Keep timing conservative when the channel is building.
```

- [ ] **Step 4: Update the route inventory README section**

```md
- `palma_ibiza`
- `palma_barcelona`
- `palma_cabrera`
- `palma_valencia`
- `ibiza_formentera`
- `alcudia_ciutadella`
- `ciutadella_palma`
- `mahon_palma`
- `formentera_palma`
```

- [ ] **Step 5: Run the route inventory and API route tests**

Run:
```bash
./.venv/bin/python -m pytest -q test_socib_scripts.py::RouteAnalysisTests test_api_app.py -k 'places_route_endpoint or routes_optimal_status or route_question_includes_route_connection_metrics or load_routes_includes_initial_platform_routes'
```
Expected: PASS with the expanded route inventory.

### Task 3: Verify and publish the topology expansion

**Files:**
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/docs/superpowers/plans/2026-06-19-spatial-route-topology-expansion.md`

- [ ] **Step 1: Run the focused checks**

Run:
```bash
./.venv/bin/python -m pytest -q test_place_weather.py::test_available_place_ids_includes_new_coastal_nodes test_socib_scripts.py::RouteAnalysisTests test_api_app.py -k 'places_route_endpoint or routes_optimal_status or route_question_includes_route_connection_metrics or load_routes_includes_initial_platform_routes'
```
Expected: PASS.

- [ ] **Step 2: Run the full repo test suite**

Run:
```bash
./.venv/bin/python -m pytest -q
```
Expected: PASS.

- [ ] **Step 3: Commit and push the topology expansion**

```bash
git add places_seed_balearics.json aliases_balearics.json data/places/places_seed_balearics.json data/places/aliases.json routes.json captain_knowledge/route_exposure_notes.yaml api/README.md test_place_weather.py test_socib_scripts.py
git commit -m "Add new coastal nodes and route topology"
git push origin main
```

## Self-Review

### Spec coverage
- New places: covered in Task 1.
- Public route expansion: covered in Task 2.
- Validation and publish: covered in Task 3.

### Placeholder scan
- No TBD/TODO placeholders.
- No vague “add validation” statements without tests.

### Type consistency
- Route IDs are ASCII and stable.
- New place IDs match the route destination/origin references.
- Tests reference the same route IDs added in the JSON files.
