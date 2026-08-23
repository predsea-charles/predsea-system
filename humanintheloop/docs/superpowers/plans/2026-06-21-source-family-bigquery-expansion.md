# Source Family BigQuery Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the single canonical BigQuery evidence table so it carries more source families from the active atmospheric, EMODnet, and Portus pipelines without changing the table split or breaking existing observations.

**Architecture:** Keep one shared evidence table and add explicit `source_family` tagging plus inventory rows for non-route data sources. The API and ETL should keep using the existing canonical pipeline, but the rows written to BigQuery must make the source family visible so we can query by atmosphere, ocean forecast, observation, radar, buoy, and provider. We will preserve the current observation and forecast paths, then add new source inventory rows where the current snapshot model is too coarse to show all available inputs.

**Tech Stack:** Python, FastAPI, JSONL validation archives, BigQuery streaming export, existing ETL pipeline modules.

---

### Task 1: Add `source_family` to canonical validation and BigQuery rows

**Files:**
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/validation_archive.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/bigquery_export.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_validation_archive.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_bigquery_export.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_observation_rows_includes_source_family():
    rows = validation_archive.build_observation_rows(
        {
            "station_a": {
                "station_name": "Station A",
                "source_system": "emodnet_physics",
                "source_label": "EMODNET_PHYSICS",
                "observed_at_utc": "2026-06-21T08:00:00Z",
                "wave_height_m": 0.7,
            }
        },
        run_date="2026-06-21",
        run_id="2026-06-21T0800Z",
    )
    assert rows[0]["source_family"] == "observation"
```

```python
def test_normalize_observation_row_keeps_source_family():
    row = bigquery_export.normalize_observation_row(
        {
            "record_type": "observation",
            "source_family": "observation",
            "provider": "emodnet_physics",
            "source_system": "emodnet_physics",
            "source_label": "EMODNET_PHYSICS",
            "station_id": "station_a",
            "station_name": "Station A",
            "variable": "wave_height",
            "value": 0.7,
            "units": "m",
        }
    )
    assert row["source_family"] == "observation"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest -q test_validation_archive.py::test_build_observation_rows_includes_source_family test_bigquery_export.py::test_normalize_observation_row_keeps_source_family
```

Expected: fail because the rows do not yet carry `source_family`.

- [ ] **Step 3: Add the canonical field and plumbing**

```python
def infer_source_family_from_record(record):
    source_system = str(record.get("source_system") or record.get("provider") or "").lower()
    source_label = str(record.get("source_label") or "").upper()
    if source_label in {"REDMAR", "REDCOS", "REDEXT", "HF_RADAR"}:
        return "observation"
    if "emodnet" in source_system or source_label == "EMODNET_PHYSICS":
        return "observation"
    if "portus" in source_system:
        return "observation"
    if "copernicus" in source_system:
        return "ocean_forecast"
    if source_system in {"meteo_france_arome", "aemet_harmonie_arome", "ecmwf_open_data"}:
        return "atmosphere"
    return "unknown"
```

Add `source_family` to:
- observation row dictionaries,
- forecast row dictionaries,
- station metadata row dictionaries,
- matched validation rows,
- BigQuery normalizers,
- and the BigQuery schema definitions for the evidence table and station metadata table.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest -q test_validation_archive.py test_bigquery_export.py
```

Expected: the new `source_family` assertions pass, and existing row-shape tests still pass.

- [ ] **Step 5: Commit**

```bash
git add validation_archive.py bigquery_export.py test_validation_archive.py test_bigquery_export.py
git commit -m "feat: tag canonical rows with source family"
```

### Task 2: Export atmospheric provider inventory rows into the same table

**Files:**
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/ingest_atmosphere.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/pipeline.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/evidence_package.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/validation_archive.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
def test_run_atmospheric_ingestion_exposes_all_provider_lineage(monkeypatch):
    fetchers = {
        "meteo_france_arome": lambda provider: {"available": True, "source": provider["id"], "label": provider["label"]},
        "aemet_harmonie_arome": lambda provider: {"available": True, "source": provider["id"], "label": provider["label"]},
        "ecmwf_open_data": lambda provider: {"available": True, "source": provider["id"], "label": provider["label"]},
    }
    monkeypatch.setattr(ingest_atmosphere, "build_fetchers", lambda output_dir=None, dry_run=False: fetchers)
    result = ingest_atmosphere.run_atmospheric_ingestion()
    assert "atmospheric_sources" in result
    assert {item["id"] for item in result["atmospheric_sources"]} == {
        "meteo_france_arome",
        "aemet_harmonie_arome",
        "ecmwf_open_data",
    }
```

```python
def test_pipeline_snapshot_carries_atmospheric_sources():
    result = pipeline.run_pipeline(dry_run=True, skip_atmosphere=False, skip_puertos=True)
    assert "atmospheric_sources" in result["snapshot"]["data_lineage"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest -q test_pipeline.py::test_pipeline_snapshot_carries_atmospheric_sources
```

Expected: fail until the atmospheric provider list is explicitly preserved in the snapshot lineage and exported as rows.

- [ ] **Step 3: Preserve all atmospheric providers and export them**

```python
def run_atmospheric_ingestion(output_dir=None, dry_run=False):
    fetchers = build_fetchers(output_dir=output_dir, dry_run=dry_run)
    provider_results = []
    for provider in ATMOSPHERIC_PROVIDERS:
        fetcher = fetchers.get(provider["id"])
        if fetcher is None:
            provider_results.append({**provider, "available": False, "error": "fetcher not configured"})
            continue
        result = fetcher(provider)
        provider_results.append({**provider, **result, "source_family": "atmosphere"})
    wind_result = next((item for item in provider_results if item.get("available")), {"available": False})
    return {
        "wind_result": wind_result,
        "wind_lineage": lineage_for_wind_result(wind_result),
        "atmospheric_sources": provider_results,
    }
```

Add a `build_source_inventory_rows()` helper in `validation_archive.py` that writes one row per atmospheric provider with:
- `record_type = "source_inventory"`
- `source_family = "atmosphere"`
- `source_system = provider id`
- `source_label = provider label`
- `value = None`
- `variable = "source_status"`
- `units = None`
- `observed_at_utc = current_timestamp_utc()`

Attach `atmospheric_sources` into `pipeline.py` snapshot lineage and `evidence_package.py` so the BigQuery export can see them.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest -q test_pipeline.py test_validation_archive.py
```

Expected: the snapshot contains atmospheric provider lineage and the inventory rows are exportable.

- [ ] **Step 5: Commit**

```bash
git add ingest_atmosphere.py pipeline.py evidence_package.py validation_archive.py test_pipeline.py
git commit -m "feat: export atmospheric provider inventory"
```

### Task 3: Confirm EMODnet Physics lands in the same table by default

**Files:**
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/ingest_observations.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/validation_archive.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/pipeline.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_ingest_observations.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_validation_archive.py`

- [ ] **Step 1: Write the failing test**

```python
def test_fetch_all_observations_includes_emodnet_by_default(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_EMODNET_OBSERVATIONS", "1")
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", "0")
    result = ingest_observations.fetch_all_observations()
    assert "emodnet_physics" in result["ground_truth_lineage"]["providers"]
```

```python
def test_station_metadata_rows_record_source_family_for_emodnet():
    rows = validation_archive.build_station_metadata_rows(
        {
            "emodnet_station": {
                "station_name": "EMODNET Station",
                "source_system": "emodnet_physics",
                "source_label": "EMODNET_PHYSICS",
                "latitude": 39.0,
                "longitude": 2.0,
                "water_temperature_c": 18.0,
            }
        },
        run_date="2026-06-21",
        run_id="2026-06-21T0800Z",
    )
    assert rows[0]["source_family"] == "observation"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest -q test_ingest_observations.py test_validation_archive.py
```

Expected: fail until EMODnet is explicitly tagged and surfaced in the canonical rows.

- [ ] **Step 3: Keep EMODnet enabled and tag it as an observation family**

```python
if include_emodnet and _emodnet_enabled():
    emodnet_result = fetch_emodnet.fetch_emodnet_bundle(dry_run=dry_run)
    emodnet_obs = emodnet_result.get("observations", {})
    if emodnet_obs:
        lineage_sources.append("emodnet_physics")
    for key, value in emodnet_obs.items():
        prefixed_key = key if key.startswith("emodnet_") else f"emodnet_{key}"
        all_observations[prefixed_key] = value
```

In `validation_archive.py`, ensure EMODnet rows carry:
- `source_family = "observation"`
- `source_system = "emodnet_physics"`
- `source_label = "EMODNET_PHYSICS"`

In `pipeline.py`, keep `include_emodnet=True` and preserve the provider in `ground_truth_lineage`.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest -q test_ingest_observations.py test_validation_archive.py
```

Expected: EMODnet appears in the lineage and its rows export with the correct source family.

- [ ] **Step 5: Commit**

```bash
git add ingest_observations.py validation_archive.py pipeline.py test_ingest_observations.py test_validation_archive.py
git commit -m "feat: land emodnet observations in canonical evidence"
```

### Task 4: Confirm Portus also lands in the same table by default

**Files:**
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/fetch_portus.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/ingest_observations.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/validation_archive.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_portus.py`
- Modify: `/Users/charles.santana/PredSea/predsea-system/humanintheloop/test_validation_archive.py`

- [ ] **Step 1: Write the failing test**

```python
def test_portus_bundle_is_kept_when_enabled(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", "1")
    result = ingest_observations.fetch_all_observations(include_puertos=False, include_emodnet=False, include_portus=True)
    assert "puertos_portus" in result["ground_truth_lineage"]["providers"]
```

```python
def test_station_metadata_rows_record_source_family_for_portus():
    rows = validation_archive.build_station_metadata_rows(
        {
            "portus_station": {
                "station_name": "Portus Station",
                "source_system": "portus",
                "source_label": "Portus station 3545",
                "latitude": 39.5,
                "longitude": 2.5,
            }
        },
        run_date="2026-06-21",
        run_id="2026-06-21T0800Z",
    )
    assert rows[0]["source_family"] == "observation"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest -q test_portus.py test_validation_archive.py
```

Expected: fail until Portus rows are explicitly tagged and included in the canonical evidence rows.

- [ ] **Step 3: Keep Portus enabled and export it through the shared table**

```python
if include_portus and _portus_enabled():
    portus_result = fetch_portus.fetch_portus_bundle(dry_run=dry_run)
    portus_obs = portus_result.get("observations", {})
    if portus_obs:
        lineage_sources.append("puertos_portus")
    for key, value in portus_obs.items():
        prefixed_key = key if key.startswith("portus_") else f"portus_{key}"
        all_observations[prefixed_key] = value
```

In `validation_archive.py`, ensure Portus rows carry:
- `source_family = "observation"`
- `source_system = "portus"`
- `source_label` from the Portus station name or station label

Keep the `include_portus=True` path in `pipeline.py` so the daily run continues to export Portus whenever it is available.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest -q test_portus.py test_validation_archive.py
```

Expected: Portus rows appear in the same BigQuery evidence stream with the right source family.

- [ ] **Step 5: Commit**

```bash
git add fetch_portus.py ingest_observations.py validation_archive.py test_portus.py test_validation_archive.py
git commit -m "feat: land portus observations in canonical evidence"
```

## Self-Review Checklist

- [x] The plan covers the shared-table requirement.
- [x] The plan covers source-family tagging before source expansion.
- [x] The plan keeps atmospheric, EMODnet, and Portus work in a clear sequence.
- [x] No placeholder text remains.
- [x] The file paths match the current codebase layout.
- [x] The plan includes concrete tests and exact commands.
