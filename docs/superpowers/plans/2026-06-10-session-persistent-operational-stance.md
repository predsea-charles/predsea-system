# Session-Persistent Operational Stance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PredSea compute one canonical operational stance per route/run so briefing text, route questions, and “what changed?” answers stay consistent unless the evidence genuinely changes.

**Architecture:** Add a shared stance object that is derived once from the evidence package and vessel context, then reused everywhere the system speaks. The stance becomes the source of truth for decision, best window, comfort, risk, confidence, and change language; briefing renderers and question responses should read the same object instead of independently re-deriving their own reasoning. When a previous run exists, a small comparison step will produce a stable `what_changed` summary without changing the stance unless the evidence materially shifts.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest, the existing `route_analysis.py`, `decision_engine.py`, `briefing_renderers.py`, and `api/` modules.

---

### Task 1: Create a canonical operational stance object

**Files:**
- Create: `operational_stance.py`
- Modify: `route_analysis.py`
- Test: `test_operational_stance.py`

- [ ] **Step 1: Write the failing tests**

```python
def sample_snapshot(wave_max):
    return {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "created_at_utc": "2026-06-09 06:30 UTC",
        "observations": {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-06-09 06:30 UTC",
                "wave_height_m": 0.4,
            }
        },
        "forecast": {
            "wave_min_m": 0.3,
            "wave_max_m": wave_max,
            "wave_peak_time": "08:00",
            "current_max_kn": 0.3,
            "current_peak_time": "15:00",
            "hourly": [
                {"time": "08:00", "wave_m": wave_max, "current_kn": 0.1},
                {"time": "17:00", "wave_m": 0.4, "current_kn": 0.3},
            ],
        },
    }


def test_operational_stance_is_stable_for_two_question_types_on_same_snapshot():
    snapshot = sample_snapshot(1.3)
    stance_a = operational_stance.build(snapshot, vessel_class="medium", current_time="07:30")
    stance_b = operational_stance.build(snapshot, vessel_class="medium", current_time="07:30")

    assert stance_a["stance_id"] == stance_b["stance_id"]
    assert stance_a["decision"] == stance_b["decision"]
    assert stance_a["best_window"] == stance_b["best_window"]
    assert stance_a["comfort"] == stance_b["comfort"]
    assert stance_a["risk"] == stance_b["risk"]
    assert stance_a["confidence"] == stance_b["confidence"]


def test_operational_stance_keeps_thresholds_internal_and_uses_natural_language():
    snapshot = sample_snapshot(1.8)
    stance = operational_stance.build(snapshot, vessel_class="small", current_time="07:30")

    assert stance["comfort"] in {"reduced comfort", "noticeable motion", "moderate", "moderate to poor"}
    assert "1.2" not in stance["comfort"]
    assert "safe" not in stance["comfort"].lower()
```

- [ ] **Step 2: Run the tests and confirm they fail for the right reason**

Run:

```bash
../.venv311/bin/python -m pytest -q test_operational_stance.py -v
```

Expected:
- fail with missing `operational_stance.build(...)` or mismatched stance fields before implementation

- [ ] **Step 3: Implement the shared stance builder**

Add `operational_stance.py` with one public entry point:

```python
def build(snapshot, vessel_class="medium", current_time=None, current_date=None, previous_stance=None):
    """Return one canonical stance dict for the supplied snapshot."""
```

Use the existing forecast, vessel profile, and freshness inputs to populate the stance. Keep vessel thresholds inside the builder; do not expose raw threshold numbers in the stance text.
The returned dict should include these keys: `stance_id`, `decision`, `best_window`, `comfort`, `risk`, `confidence`, `what_changed`, `evidence_timestamp`, `freshness_status`, `freshness_warning`, and `why`.

Update `route_analysis.py` so the snapshot that drives the rest of the app carries both:

```python
snapshot["operational_stance"] = stance
snapshot["recommendation"] = stance  # compatibility alias during rollout
```

- [ ] **Step 4: Run the tests again**

Run:

```bash
../.venv311/bin/python -m pytest -q test_operational_stance.py test_route_analysis.py -v
```

Expected:
- both tests pass

- [ ] **Step 5: Commit**

```bash
git add operational_stance.py route_analysis.py test_operational_stance.py
git commit -m "Add canonical operational stance builder"
```

### Task 2: Make all route answers reuse the same stance

**Files:**
- Modify: `api/services.py`
- Modify: `api/app.py`
- Modify: `decision_engine.py`
- Modify: `briefing_renderers.py`
- Modify: `api/schemas.py`
- Test: `test_api_app.py`
- Test: `test_socib_scripts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_route_question_and_briefing_share_the_same_stance(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    briefing = client.get("/routes/palma_ibiza/briefing?date=2026-05-29&format=whatsapp").json()
    question = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-05-29",
            "question": "When is the best moment to leave from Palma to Ibiza today?",
            "vessel_class": "medium",
            "location_label": "Palma Marina",
            "current_time": "09:30",
        },
    ).json()

    assert briefing["operational_stance"]["stance_id"] == question["operational_stance"]["stance_id"]
    assert briefing["operational_stance"]["decision"] == question["operational_stance"]["decision"]
    assert briefing["operational_stance"]["best_window"] == question["operational_stance"]["best_window"]


def test_two_different_questions_return_the_same_operational_stance(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    first = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-05-29",
            "question": "Would Palma to Ibiza feel comfortable for a 12m vessel tomorrow morning?",
            "vessel_class": "small",
            "location_label": "Palma",
            "current_time": "09:30",
        },
    ).json()
    second = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-05-29",
            "question": "When is the best time to leave from Palma to Ibiza today?",
            "vessel_class": "small",
            "location_label": "Palma",
            "current_time": "09:30",
        },
    ).json()

    assert first["operational_stance"]["stance_id"] == second["operational_stance"]["stance_id"]
    assert first["answer"].split("\n\n")[0] == second["answer"].split("\n\n")[0]
```

- [ ] **Step 2: Run the tests to confirm the current API still re-derives answers separately**

Run:

```bash
../.venv311/bin/python -m pytest -q test_api_app.py -k "operational_stance or question_endpoint or briefing_endpoint" -v
```

Expected:
- the new stance-sharing assertions fail until the response plumbing is updated

- [ ] **Step 3: Thread the stance through the API and rendering layer**

Update `api/services.py` so `snapshot_for_vessel_class(...)` attaches one stance object and `answer_question(...)` reuses it instead of asking `decision_engine` to recompute a separate recommendation per question. Update `decision_engine.py` so `answer_question(...)` formats the final text from `snapshot["operational_stance"]` and the question intent, rather than branching into a fresh comfort/risk recommendation path for each question type.
Update `api/app.py` so the briefing and question route handlers return the same `operational_stance` object in their JSON payloads, allowing the WhatsApp layer to reuse the exact same stance across follow-ups.

Update `briefing_renderers.py` so WhatsApp and LinkedIn briefs read the same stance fields:

```python
stance = snapshot["operational_stance"]
decision = stance["decision"]
best_window = stance["best_window"]
comfort = stance["comfort"]
risk = stance["risk"]
confidence = stance["confidence"]
```

Update `api/schemas.py` so the route question response can return the stance object explicitly:

```python
class QuestionResponse(BaseModel):
    route_id: str
    route: str
    date: str
    run: Optional[str] = None
    question: str
    answer: str
    intent: str
    evidence_timestamp: Optional[str] = None
    freshness_status: str
    freshness_warning: Optional[str] = None
    captain_knowledge: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_used: Dict[str, Any]
    operational_stance: Dict[str, Any]


class BriefingResponse(BaseModel):
    route_id: str
    route: str
    date: str
    run: Optional[str] = None
    format: Literal["whatsapp", "linkedin"]
    briefing: str
    operational_stance: Dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run the API-focused tests again**

Run:

```bash
../.venv311/bin/python -m pytest -q test_api_app.py test_socib_scripts.py -v
```

Expected:
- briefing and question surfaces expose the same stance
- comfort wording stays qualitative and non-contradictory
- no raw threshold numbers appear in the user-facing answer text

- [ ] **Step 5: Commit**

```bash
git add api/services.py decision_engine.py briefing_renderers.py api/schemas.py test_api_app.py test_socib_scripts.py
git commit -m "Reuse one operational stance across PredSea answers"
```

### Task 3: Add a stable "what changed?" comparison

**Files:**
- Modify: `api/services.py`
- Modify: `api/app.py`
- Modify: `api/evidence_store.py`
- Modify: `decision_engine.py`
- Modify: `api/schemas.py`
- Modify: `scripts/generate_daily_briefing.py`
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_question_endpoint_reports_no_operational_change_when_latest_run_matches_previous_run(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-06-05T0630Z", wave_max=1.0, created_at_utc="2026-06-05 06:30 UTC")
    write_run_snapshot(tmp_path, run_id="2026-06-05T1230Z", wave_max=1.0, created_at_utc="2026-06-05 12:30 UTC")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-05",
            "run": "latest",
            "question": "Has anything changed since this morning?",
            "vessel_class": "medium",
            "current_date": "2026-06-05",
            "current_time": "12:00",
        },
    ).json()

    assert response["operational_stance"]["what_changed"] == "No operational change."
    assert "No operational change." in response["answer"]


def test_question_endpoint_reports_a_material_change_when_the_latest_run_is_rougher(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-06-05T0630Z", wave_max=0.8, created_at_utc="2026-06-05 06:30 UTC")
    write_run_snapshot(tmp_path, run_id="2026-06-05T1230Z", wave_max=1.5, created_at_utc="2026-06-05 12:30 UTC")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-05",
            "run": "latest",
            "question": "Has anything changed since this morning?",
            "vessel_class": "medium",
            "current_date": "2026-06-05",
            "current_time": "12:00",
        },
    ).json()

    assert response["operational_stance"]["what_changed"] != "No operational change."
    assert "recommendation remains the same" in response["answer"].lower() or "bring the preferred departure forward" in response["answer"].lower()
```

- [ ] **Step 2: Run the tests and confirm the comparison behavior is still missing**

Run:

```bash
../.venv311/bin/python -m pytest -q test_api_app.py -k "change or changed" -v
```

Expected:
- the change-specific assertions fail until the comparison helper is implemented

- [ ] **Step 3: Implement the comparison helper and backfill the stance into run artifacts**

Add a small comparison path that reads the previous available stance for the same route and date, then emits one short operational delta:

```python
def compare_operational_stances(previous, current):
    return {
        "material_change": False,
        "summary": "No operational change.",
    }
```

When a real change is detected, keep the output qualitative:

```python
{
    "material_change": True,
    "summary": "The afternoon deterioration is now expected earlier than this morning.",
}
```

Update `scripts/generate_daily_briefing.py` so the daily run archive stores the canonical stance object alongside the existing briefing and validation artifacts. That gives the API a single source of truth for both the current response and the next comparison.
Add a small helper pair to `api/evidence_store.py` so the API can enumerate run ids for a date and then find the immediately previous run without guessing from filenames alone:

```python
def available_runs(self, run_date=None):
    date_text = self.resolve_date(run_date)
    day_dir = self.predictions_root / date_text / "runs"
    if not day_dir.exists():
        return []
    return sorted(path.name for path in day_dir.iterdir() if path.is_dir())


def previous_run(self, run_date=None, run_id=None):
    runs = self.available_runs(run_date)
    current = self.resolve_run(run_date, run_id)
    if not current or current not in runs:
        return None
    index = runs.index(current)
    if index == 0:
        return None
    return runs[index - 1]
```

Mirror the same `available_runs` and `previous_run` behavior in `GcsEvidenceStore` so the comparison works the same whether the API is reading from local predictions or from Google Cloud Storage.

- [ ] **Step 4: Run the tests again**

Run:

```bash
../.venv311/bin/python -m pytest -q test_api_app.py -v
```

Expected:
- the change-response tests pass
- the API returns the same stance and the same operational delta for briefing and follow-up answers

- [ ] **Step 5: Commit**

```bash
git add api/services.py decision_engine.py api/schemas.py scripts/generate_daily_briefing.py test_api_app.py
git commit -m "Add operational change comparison to PredSea answers"
```

### Task 4: Document the stance contract for API consumers

**Files:**
- Modify: `api/README.md`
- Modify: `docs/prediction-etl.md`
- Modify: `docs/bigquery-evidence-rows.md`

- [ ] **Step 1: Write the documentation checks**

Add a short example showing the new shared stance fields in the route question response:

```json
{
  "intent": "leave_window",
  "operational_stance": {
    "stance_id": "palma_ibiza:2026-06-05T0755Z:medium",
    "decision": "CAUTION",
    "best_window": "before late morning",
    "comfort": "moderate",
    "risk": "low",
    "confidence": "Medium",
    "what_changed": "No operational change."
  }
}
```

Add one note that the operational stance is the same object reused by briefing, route conditions, and follow-up questions, so clients should not expect conflicting recommendations for the same route/run unless a new evidence package arrives.

- [ ] **Step 2: Update the docs and verify the examples still match the API**

Run:

```bash
../.venv311/bin/python -m pytest -q test_api_app.py test_socib_scripts.py -v
```

Expected:
- the documented examples match the current API responses
- no user-facing text exposes internal vessel thresholds or hidden confidence math

- [ ] **Step 3: Commit**

```bash
git add api/README.md docs/prediction-etl.md docs/bigquery-evidence-rows.md
git commit -m "Document the operational stance contract"
```
