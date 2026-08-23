# Task List: PredSea Phase 3 Ingestion, Anomalies & Orchestration

## Phase 3: Mediterranean-Wide Observation Scale-up & Daily Orchestration

- [x] **Task 3.1: Expand EMODnet Physics Ingestion**
  - [x] Apply spatial bounding coordinates (Latitude `[30.0, 46.0]`, Longitude `[-10.0, 30.0]`) in `etl.py`
  - [x] Ensure robust parsing and typing of columns
  - [x] Verify using `pytest humanintheloop/test_emodnet_physics.py`

- [x] **Task 3.2: Climatology Anomaly Check & Alerts Ingestion**
  - [x] Create `scripts/climatology_anomaly_check.py` to run queries against `climatology_baseline`
  - [x] Calculate Z-scores for `water_temperature`, `salinity`, and `sea_level`
  - [x] Format alerts and trigger HTTP POST to the Cloud Run warnings endpoint
  - [x] Implement `POST /warnings/active` route in `api/routers/warnings_endpoint.py`
  - [x] Update `GET /warnings/active` to serve both pre-computed pushed alerts and fallback BigQuery queries

- [x] **Task 3.3: Master Daily Orchestrator**
  - [x] Create `scripts/daily_orchestrator.py`
  - [x] Wire up boundaries downloading, Spot VM execution tracking, observation ingestion, and anomaly checks
  - [x] Build in safety controls: Spot VM self-deletion on completion or failure

- [x] **Task 3.4: Live Cloud Run Verification**
  - [x] Verify the GCS-based `GcsEvidenceStore` properly reads custom WRF/ROMS forecasts from `PREDSEA_GCS_BUCKET`

## Phase 4: BigQuery Schema Migration & Cloud Deployment
- [x] **Task 4.1: Diagnose BigQuery Schema Mismatch**
  - [x] Analyze schema mismatch on `evidence_rows` (missing `freshness_status` and 23 other fields)
- [x] **Task 4.2: Execute Schema Migration**
  - [x] Create and run `migrate_schema.py` to update live table to full 54-field layout
  - [x] Update `scripts/climatology_anomaly_check.py` to select `latitude`/`longitude` for richer warnings
- [/] **Task 4.3: Deploy and Execute Job**
  - [ ] Deploy updated code to GCP Cloud Run Job using `deploy_cloud_run.sh`
  - [ ] Execute manual run of `daily-orchestrator` and monitor to a successful finish

