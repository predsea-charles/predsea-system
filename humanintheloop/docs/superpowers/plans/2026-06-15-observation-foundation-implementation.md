# Observation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make observation ingestion source-specific, timestamp-strict, and schema-consistent across SOCIB, REDEXT, REDCOS, and REDMAR.

**Architecture:** Keep the existing ETL shape, but tighten the observation branch. Each source connector will parse its own timestamps and QC hints, normalize into a shared observation schema, and reject future-dated samples from the live layer. Validation export will carry explicit provenance fields and a small station metadata table so the API and future fusion layers can reason about source quality without inventing time.

**Tech Stack:** Python 3.13, xarray, pandas, FastAPI, BigQuery export, JSONL run artifacts, pytest.

---

### Task 1: Add source timestamp and freshness helpers

**Files:**
- Modify: `predsea/connectors/puertos_del_estado/common.py`
- Modify: `place_weather.py`
- Modify: `socib_api.py`
- Modify: `observation_alignment.py`
- Test: `test_puertos_estado.py`
- Test: `test_place_weather.py`
- Test: `test_validation_archive.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_puertos_latest_value_skips_future_times():
    # a value at 23:59:59Z should be ignored when "now" is earlier
    ...

def test_place_weather_marks_future_observation_unknown():
    # future observation timestamps should produce freshness_status == "unknown"
    ...

def test_validation_archive_drops_future_observation_rows():
    # a future observation should not be exported as a live validation row
    ...
```

- [ ] **Step 2: Run the targeted tests and confirm they fail**

Run: `./.venv/bin/python -m pytest -q test_puertos_estado.py -k future or latest_value`

Expected: FAIL before implementation because the helper still trusts the last time coordinate.

- [ ] **Step 3: Implement the minimal timestamp and freshness guards**

```python
def latest_value_from_dataarray(da, *, latitude=None, longitude=None, now_utc=None):
    ...
    if parsed_time is not None and parsed_time > now_utc + timedelta(minutes=5):
        return None, None

def normalize_observation(record, station_id=None, generated_at_utc=None):
    ...
    if observed_at is not None and observed_at > generated_at + timedelta(minutes=5):
        normalized["last_sample_utc"] = None
        normalized["observed_at_utc"] = None
        normalized["source_time_coordinate_utc"] = None

def freshness_state_from_age(age_minutes):
    ...
```

- [ ] **Step 4: Run the targeted tests and confirm they pass**

Run: `./.venv/bin/python -m pytest -q test_puertos_estado.py -k future or latest_value && ./.venv/bin/python -m pytest -q test_place_weather.py -k future or freshness && ./.venv/bin/python -m pytest -q test_validation_archive.py -k future`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add predsea/connectors/puertos_del_estado/common.py place_weather.py socib_api.py observation_alignment.py test_puertos_estado.py test_place_weather.py test_validation_archive.py
git commit -m "feat: tighten observation timestamps"
```

### Task 2: Normalize Puertos observations with explicit provenance

**Files:**
- Modify: `predsea/connectors/puertos_del_estado/redext_parser.py`
- Modify: `predsea/connectors/puertos_del_estado/redcos_parser.py`
- Modify: `predsea/connectors/puertos_del_estado/redmar_parser.py`
- Modify: `predsea/connectors/puertos_del_estado/normalizer.py`
- Modify: `predsea/connectors/puertos_del_estado/etl.py`
- Test: `test_puertos_estado.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_redext_parser_emits_source_coordinate_timestamp():
    ...

def test_redmar_parser_keeps_sea_level_only():
    ...

def test_puertos_normalizer_emits_qc_and_freshness_fields():
    ...
```

- [ ] **Step 2: Run the targeted tests and confirm they fail**

Run: `./.venv/bin/python -m pytest -q test_puertos_estado.py -k redext or redmar or normalizer`

Expected: FAIL until parser records include explicit source time and freshness/provenance fields.

- [ ] **Step 3: Update the parser outputs**

```python
record = {
    "provider": "puertos_del_estado",
    "network": "redext",
    "source_label": "REDEXT",
    "source_field": source_field,
    "source_time_coordinate_utc": sample_time,
    "sample_time_utc": sample_time,
    "observed_at_utc": sample_time,
    "qc_flag": qc_flag,
    "is_qc_good": qc_flag in (1, 2),
    "is_future": False,
}
```

- [ ] **Step 4: Run the targeted tests and confirm they pass**

Run: `./.venv/bin/python -m pytest -q test_puertos_estado.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add predsea/connectors/puertos_del_estado/redext_parser.py predsea/connectors/puertos_del_estado/redcos_parser.py predsea/connectors/puertos_del_estado/redmar_parser.py predsea/connectors/puertos_del_estado/normalizer.py predsea/connectors/puertos_del_estado/etl.py test_puertos_estado.py
git commit -m "feat: normalize puertos observation provenance"
```

### Task 3: Add station metadata output and docs

**Files:**
- Modify: `scripts/generate_daily_briefing.py`
- Modify: `validation_archive.py`
- Modify: `api/README.md`
- Modify: `docs/api-whatsapp.md`
- Test: `test_run_based_outputs.py`
- Test: `test_validation_archive.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_daily_generator_writes_station_metadata():
    ...

def test_validation_archive_includes_station_metadata_rows():
    ...
```

- [ ] **Step 2: Run the targeted tests and confirm they fail**

Run: `./.venv/bin/python -m pytest -q test_run_based_outputs.py -k station_metadata or test_validation_archive.py -k station_metadata`

Expected: FAIL until the ETL writes the metadata artifact.

- [ ] **Step 3: Write the metadata artifact**

```python
station_metadata = {
    station_id: {
        "provider": ...,
        "network": ...,
        "station_name": ...,
        "latitude": ...,
        "longitude": ...,
        "variables_supported": [...],
    }
}
```

- [ ] **Step 4: Run the targeted tests and confirm they pass**

Run: `./.venv/bin/python -m pytest -q test_run_based_outputs.py test_validation_archive.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_daily_briefing.py validation_archive.py api/README.md docs/api-whatsapp.md test_run_based_outputs.py test_validation_archive.py
git commit -m "feat: add observation station metadata"
```

## Coverage Check

- Task 1 covers timestamp strictness, future-dated rejection, and freshness behavior.
- Task 2 covers source-specific provenance, QC, and the unified observation row shape.
- Task 3 covers the new station metadata table/artifact and the user-facing docs.

## Notes

- HF radar and observation fusion are intentionally out of scope for this phase.
- The live API should continue to read the canonical observation layer without
  inventing timestamps or source fields.

