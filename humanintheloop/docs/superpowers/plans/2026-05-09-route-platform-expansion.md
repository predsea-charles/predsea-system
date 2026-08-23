# Route Platform Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand PredSea from a single Palma-Ibiza MVP route into a route-aware briefing platform with vessel-class advice.

**Architecture:** Add `routes.json` as the catalog, load selected routes in `route_analysis.py`, pass route and vessel class through `briefing.py`, and keep existing renderers consuming the snapshot shape. Output artifacts move into route-specific folders under `mvp_data/routes/<route_id>/`.

**Tech Stack:** Python standard library, existing `unittest` suite, existing Copernicus/SOCIB scripts, optional `xarray` path already used by forecast sampling.

---

### Task 1: Route Catalog

**Files:**
- Create: `routes.json`
- Modify: `route_analysis.py`
- Test: `test_socib_scripts.py`

- [ ] Add a failing test that loads route IDs and verifies Palma-Ibiza and Alcudia-Ciutadella sample points exist.
- [ ] Implement `load_routes()` and `load_route(route_id)`.
- [ ] Add `routes.json` with four initial route records.
- [ ] Run `./.venv/bin/python -m unittest test_socib_scripts.py`.

### Task 2: Route-Agnostic Forecast Sampling

**Files:**
- Modify: `route_analysis.py`
- Test: `test_socib_scripts.py`

- [ ] Add a failing test proving forecast sampling uses the supplied route sample points instead of the old hard-coded constant.
- [ ] Change `forecast_summary_from_files()` to accept a route record.
- [ ] Preserve route-exposed max behavior and the existing fallback summary.
- [ ] Run `./.venv/bin/python -m unittest test_socib_scripts.py`.

### Task 3: Vessel Class Advice

**Files:**
- Modify: `route_analysis.py`
- Modify: `decision_engine.py`
- Test: `test_socib_scripts.py`

- [ ] Add failing tests showing small-vessel advice is more restrictive than large-vessel advice for the same forecast.
- [ ] Add vessel class thresholds in `route_analysis.py`.
- [ ] Include `vessel_class`, `vessel_profile`, and vessel-sensitive severity in the snapshot recommendation.
- [ ] Teach `decision_engine.py` to include vessel class context in direct answers.
- [ ] Run `./.venv/bin/python -m unittest test_socib_scripts.py`.

### Task 4: Route-Specific Outputs and CLI

**Files:**
- Modify: `briefing.py`
- Test: `test_socib_scripts.py`

- [ ] Add failing tests for route-specific output folder naming.
- [ ] Add CLI arguments `--route`, `--vessel-class`, and `--list-routes`.
- [ ] Write artifacts to `mvp_data/routes/<route_id>/`.
- [ ] Keep existing `write_outputs(snapshot, output_dir=...)` tests working for custom output paths.
- [ ] Run `./.venv/bin/python -m unittest test_socib_scripts.py`.

### Task 5: Verification

**Files:**
- Read: all changed files

- [ ] Run the full unit test suite.
- [ ] Inspect generated route catalog and snapshot structure.
- [ ] Summarize commands, changed files, and remaining caveats.
