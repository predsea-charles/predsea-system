# Captain Knowledge and Route Segments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn PredSea's route answers from forecast summaries into co-captain recommendations that combine forecast evidence, route exposure, vessel context, and structured captain knowledge.

**Architecture:** Keep the current API endpoints stable. Add a small `captain_knowledge.py` loader and structured knowledge files under `humanintheloop/captain_knowledge/`. Add route segment summaries to `route_analysis.py`, include them in `evidence.json`, and let `decision_engine.py` mention worst segment and applicable captain rules.

**Tech Stack:** Python standard library JSON/YAML-compatible parsing, existing route/evidence modules, pytest.

---

### Task 1: Captain Knowledge Contract

**Files:**
- Create: `humanintheloop/captain_knowledge/graham_rules.yaml`
- Create: `humanintheloop/captain_knowledge/graham_cases.json`
- Create: `humanintheloop/captain_knowledge/vessel_thresholds.yaml`
- Create: `humanintheloop/captain_knowledge/route_exposure_notes.yaml`
- Create: `humanintheloop/captain_knowledge.py`
- Test: `humanintheloop/test_captain_knowledge.py`

- [ ] Write a test that loads rules, vessel thresholds, route notes, and cases.
- [ ] Implement the loader with deterministic rule matching by route, vessel class, sea-state label, wave height, and forecast horizon.
- [ ] Verify rules are structured with `id`, `condition`, `operational_consequence`, `preferred_action`, and `confidence`.

### Task 2: Route Segment Evidence

**Files:**
- Modify: `humanintheloop/route_analysis.py`
- Modify: `humanintheloop/evidence_package.py`
- Test: `humanintheloop/test_route_analysis.py`

- [ ] Write a test that a route forecast summary includes `route_segments`.
- [ ] Implement departure/open-water/arrival segment summaries from route sample points.
- [ ] Identify `worst_segment` by max wave height and include `best_departure_window`.
- [ ] Include route segments in `evidence.json`.

### Task 3: Decision Engine Uses Knowledge

**Files:**
- Modify: `humanintheloop/decision_engine.py`
- Modify: `humanintheloop/api/services.py`
- Test: `humanintheloop/test_decision_engine.py`

- [ ] Write a test that a Palma-Ibiza small-vessel NW/channel case mentions the open-water or channel watch-out.
- [ ] Apply matching captain rules to snapshot context before rendering the answer.
- [ ] Keep the answer hierarchy stable: Decision, Best window, Comfort, Risk, Why, What could change, Confidence.
- [ ] Avoid repeating the same sentence between sections.

### Task 4: Documentation and Verification

**Files:**
- Modify: `docs/prediction-etl.md`
- Modify: `humanintheloop/api/README.md` if response metadata changes

- [ ] Document where to add Graham rules, route exposure notes, and captain cases.
- [ ] Run focused tests and the existing API/ETL suite.
- [ ] Commit and push a clean slice.
