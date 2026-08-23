# Route Reliability Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a request-time `reliability` block to `POST /routes/{route_id}/question` using route snapshot evidence plus latest place-weather evidence.

**Architecture:** Add one small API helper that loads the relevant place-weather records, computes freshness age and variance/consistency, and returns a conservative score. Wire it into the route-question handler and expose the block in `QuestionResponse` without changing any database or ETL formats.

**Tech Stack:** Python, FastAPI, Pydantic, existing `EvidenceStore`, existing route snapshot and place-weather helpers, `pytest`.

---

### Task 1: Add reliability helper

**Files:**
- Create: `api/reliability.py`
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_route_question_includes_reliability(tmp_path):
    # route snapshot with one observation and one latest place-weather file
    # should return a reliability block with score, method, and age_minutes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k reliability`

Expected: fail because `reliability` is missing.

- [ ] **Step 3: Write minimal implementation**

```python
def compute_route_reliability(store, route_id, run_date, run_id, snapshot):
    return {
        "confidence_score": "Low",
        "evaluation_method": "single_model_consistency",
        "age_minutes": 999,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k reliability`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/reliability.py test_api_app.py
git commit -m "feat: add route reliability helper"
```

### Task 2: Wire response schema and endpoint

**Files:**
- Modify: `api/schemas.py`
- Modify: `api/app.py`
- Modify: `api/services.py` if needed
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_route_question_reliability_method_changes_with_data():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k route_question_reliability`

- [ ] **Step 3: Write minimal implementation**

Add `reliability` to `QuestionResponse`, compute it in the route-question handler, and return it in the JSON payload.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest -q test_api_app.py -k route_question_reliability`

- [ ] **Step 5: Commit**

```bash
git add api/schemas.py api/app.py api/services.py test_api_app.py
git commit -m "feat: expose route reliability in question response"
```

### Task 3: Verify and document

**Files:**
- Modify: `api/README.md`
- Test: `test_api_app.py`

- [ ] **Step 1: Run the focused API tests**

Run: `./.venv/bin/python -m pytest -q test_api_app.py`

- [ ] **Step 2: Update docs if the new block needs a short note**

```md
The route-question response now includes a reliability block with confidence_score, evaluation_method, and age_minutes.
```

- [ ] **Step 3: Commit**

```bash
git add api/README.md
git commit -m "docs: mention route reliability block"
```
