# Place Hierarchy and Static Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a place hierarchy with Palma as the main default port, expose selected Palma sub-ports as separate places, and add a reusable static metrics layer for distance and typical travel time between places.

**Architecture:** Keep the existing place-weather API surface, but move place definitions, parent-child relations, observation candidate lists, and static pair metrics into a small registry module. `place_weather.py` will consume that registry so place resolution, observation selection, and future distance lookups all use the same source of truth. The API will remain weather-first, with no recommendation logic added.

**Tech Stack:** Python, FastAPI, pytest, existing evidence-store and place-weather modules.

---

### Task 1: Add a place registry with hierarchy and static metrics

**Files:**
- Create: `place_registry.py`
- Test: `test_place_weather.py`

- [ ] **Step 1: Write the failing test**

```python
from place_registry import (
    available_place_ids,
    default_place_id_for_query,
    place_definition,
    place_pair_metrics,
    station_candidates_for_place,
)


def test_palma_has_child_ports_and_defaults_to_main_place():
    assert default_place_id_for_query("Palma") == "palma"
    assert place_definition("palma")["parent_place_id"] is None
    assert place_definition("port_de_palma")["parent_place_id"] == "palma"
    assert place_definition("port_adriano")["parent_place_id"] == "palma"
    assert place_definition("can_pastilla")["parent_place_id"] == "palma"
    assert "port_de_palma" in available_place_ids()


def test_place_pair_metrics_return_distance_and_time():
    metrics = place_pair_metrics("palma", "portocolom")
    assert metrics["origin_place_id"] == "palma"
    assert metrics["destination_place_id"] == "portocolom"
    assert metrics["distance_nm"] > 0
    assert metrics["typical_travel_time_minutes"] > 0


def test_station_candidates_are_explicit_and_ordered():
    candidates = station_candidates_for_place("portocolom")
    assert candidates[:2] == ["porto_colom", "alcudia"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q test_place_weather.py -k 'palma_has_child_ports or place_pair_metrics or station_candidates_are_explicit'
```

Expected: FAIL because `place_registry.py` and its helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# place_registry.py should export:
# - PLACE_CATALOG with canonical places and parent_place_id values
# - DEFAULT_PLACES_BY_QUERY so "Palma" resolves to "palma"
# - OBSERVATION_CANDIDATES with ordered station ids for each place
# - PAIR_METRICS with precomputed distance_nm and travel-time facts
# - place_pair_metrics(origin_place_id, destination_place_id)
# - station_candidates_for_place(place_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q test_place_weather.py -k 'palma_has_child_ports or place_pair_metrics or station_candidates_are_explicit'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add place_registry.py test_place_weather.py
git commit -m "Add place registry and static metrics"
```

### Task 2: Refactor place weather to use the registry

**Files:**
- Modify: `place_weather.py`
- Test: `test_place_weather.py`

- [ ] **Step 1: Write the failing test**

```python
def test_place_weather_uses_registry_definitions():
    from place_weather import place_definition, select_observation_for_place

    assert place_definition("port_de_palma")["parent_place_id"] == "palma"
    selected = select_observation_for_place(
        "portocolom",
        {"porto_colom": {"station_id": "porto_colom", "station_name": "Portocolom", "wave_height_m": 0.7}},
    )
    assert selected["station_id"] == "porto_colom"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q test_place_weather.py -k 'uses_registry_definitions'
```

Expected: FAIL until `place_weather.py` imports the registry and supports the new place IDs.

- [ ] **Step 3: Write minimal implementation**

```python
from place_registry import PLACE_CATALOG, available_place_ids, default_place_id_for_query, place_definition, place_pair_metrics, station_candidates_for_place
```

Update `place_weather.py` so:

- `available_place_ids()` delegates to the registry
- `place_definition()` reads the registry
- `select_observation_for_place()` uses `station_candidates_for_place(place_id)`
- `build_place_weather_record()` adds `parent_place_id` and `place_kind` metadata
- a helper like `place_connection_metrics(origin_place_id, destination_place_id)` returns the static pair metrics

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q test_place_weather.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add place_weather.py test_place_weather.py
git commit -m "Refactor place weather to use place registry"
```

### Task 3: Document and verify the new place model

**Files:**
- Modify: `docs/api-whatsapp.md`
- Modify: `api/README.md`
- Modify: `docs/superpowers/specs/2026-06-13-place-hierarchy-and-static-metrics-design.md` if any clarifications are needed
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_place_weather_endpoint_accepts_new_palma_subports(tmp_path):
    write_place_weather(tmp_path, place_id="port_de_palma")
    app = create_app(...)
    client = TestClient(app)
    response = client.get("/places/port_de_palma/weather?date=2026-05-31&run=latest")
    assert response.status_code == 200
    assert response.json()["place_id"] == "port_de_palma"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q test_api_app.py -k 'port_de_palma'
```

Expected: FAIL until the place registry and API docs are updated.

- [ ] **Step 3: Write minimal implementation**

```markdown
Update the docs to list the Palma family:
- `palma`
- `port_de_palma`
- `port_adriano`
- `can_pastilla`

Add a short note that `palma` is the default general Palma place and specific ports are exposed separately.
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q test_api_app.py -k 'port_de_palma'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/README.md docs/api-whatsapp.md test_api_app.py
git commit -m "Document Palma place hierarchy"
```

## Self-Review Checklist

- The plan covers the new Palma parent/child place model.
- The plan covers static distance and travel-time metrics.
- The plan keeps observation selection explicit and station-first.
- The plan keeps the API weather-first and avoids recommendation logic.
- The plan uses concrete files, tests, and commands.
