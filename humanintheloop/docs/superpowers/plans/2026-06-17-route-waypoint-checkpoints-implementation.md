# PredSea Route Waypoint + Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the route geometry endpoint so it returns minimalist waypoints plus a parallel checkpoint timeline with ETA and sampled weather at each checkpoint.

**Architecture:** Keep `searoute` as the geometry source, derive checkpoints from the returned path, and sample weather per checkpoint from the existing place-weather snapshot path. The geometry stays clean; timing and weather live in a parallel array.

**Tech Stack:** FastAPI, Pydantic, `searoute`, existing PredSea evidence store and place-weather helpers.

---

### Task 1: Extend the route schema

**Files:**
- Modify: `api/schemas.py`

- [ ] **Step 1: Add a checkpoint model and extend the response**

```python
class RouteWaypointCheckpoint(BaseModel):
    waypoint_index: int
    lat: float
    lng: float
    eta_utc: str
    distance_from_origin_nm: float
    forecast_time_utc: str
    weather: Dict[str, Any] = Field(default_factory=dict)


class RouteWaypointsResponse(BaseModel):
    ...
    checkpoints: List[RouteWaypointCheckpoint] = Field(default_factory=list)
```

### Task 2: Build checkpoints in the route endpoint

**Files:**
- Modify: `api/app.py`

- [ ] **Step 1: Add `date`, `run`, and `departure_time` query params to `/places/route/{origin}/{destination}`**
- [ ] **Step 2: Compute cumulative waypoint distances and ETAs**
- [ ] **Step 3: Sample weather at each checkpoint ETA using the existing place-weather snapshot path**
- [ ] **Step 4: Return `waypoints` and `checkpoints` in the same response**

### Task 3: Update docs and tests

**Files:**
- Modify: `api/README.md`
- Modify: `docs/api-whatsapp.md`
- Modify: `test_api_app.py`

- [ ] **Step 1: Document the checkpoint timeline and ETA/weather sampling**
- [ ] **Step 2: Add route endpoint tests for `checkpoints` and coordinate overrides**
- [ ] **Step 3: Run the focused route tests and the API build check**
