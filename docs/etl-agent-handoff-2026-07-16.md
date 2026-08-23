# PredSea ETL Agent Handoff — 2026-07-16

This document is the operational handoff for continuing the PredSea ETL reliability work with another AI agent. Read it together with [`etl-definitive-solution-plan.md`](./etl-definitive-solution-plan.md).

## Safety rules for the next agent

1. Read repository `AGENTS.md` and `.agents/skills/gcloud/SKILL.md` before any `gcloud` command.
2. Run `gcloud help <exact leaf command>` before executing that command, as required by the repository skill.
3. Do not deploy from the main workspace: it has unrelated user changes. Build from a clean commit/worktree.
4. Do not modify `predsea-api`, `daily-orchestrator`, `predsea-daily-outputs`, production traffic, or the scheduler until staging passes all gates below.
5. Never print or commit `.env` values. Several third-party credentials are currently supplied as Cloud Run environment variables. Move them to Secret Manager and rotate exposed credentials as a separate security task.
6. Do not delete staging or diagnostic resources without explicit user authorization.

## Repository and release identifiers

- Project: `predsea-api`
- Region: `europe-west1`
- Branch: `main`
- Reliability commit: `b5d5f2c` (`fix: publish forecasts before optional analytics`)
- Commit pushed to `origin/main`: yes
- Staging image digest: `sha256:d9a947bc03f877b16c7536f4db0f0e93741bbef8f8148427266bd7bec5fb589a`
- Image reference: `europe-west1-docker.pkg.dev/predsea-api/cloud-run-source-deploy/predsea-api@sha256:d9a947bc03f877b16c7536f4db0f0e93741bbef8f8148427266bd7bec5fb589a`
- Clean temporary worktree used for build: `/private/tmp/predsea-deploy-b5d5f2c`
- Cloud Build ID: `ea2dd5a3-1dfb-40fc-bf78-7d0bf54473dd`
- Cloud Build result: `SUCCESS`

## Production state

Production was not deployed or reconfigured during the staging rollout described here.

- API service: `predsea-api`
- API URL: `https://predsea-api-193957983101.europe-west1.run.app`
- ETL job: `daily-orchestrator`
- Output bucket: `predsea-daily-outputs`
- Scheduler target time requested by user: `05:00 Europe/Madrid`
- Last observed production health on 2026-07-16:

```json
{
  "status": "ok",
  "latest_date": "2026-07-16",
  "latest_run": "manual_recovery",
  "storage_backend": "gcs",
  "environment": "prod"
}
```

The `manual_recovery` production pointer appeared independently of this staging deployment. Determine its provenance before changing production, but do not assume staging caused it: staging uses a separate service, job, and bucket.

## Staging resources

- API service: `predsea-api-test`
- API URL: `https://predsea-api-test-193957983101.europe-west1.run.app`
- API revision: `predsea-api-test-00005-lnz`
- Publication job: `predsea-publication-test`
- Publication execution: `predsea-publication-test-b7qbf`
- Test bucket: `predsea-daily-outputs-test`
- Test BigQuery dataset setting: `predsea_validation_test`
- Retained WRF input copied to staging:
  `gs://predsea-daily-outputs-test/predictions/2026-07-15/runs/2026-07-15T1551Z/atmosphere/wrf_d02.nc`

The staging API and job use the staging image digest above. They do not receive production traffic and do not write to the production bucket.

## Staging execution result

Execution `predsea-publication-test-b7qbf` completed successfully:

- Started: `2026-07-15T22:33:17Z`
- Completed: `2026-07-15T23:08:12Z`
- Duration reported by Cloud Run: `35m10.79s`
- Tasks succeeded: `1`
- Core publication used `--skip-figures --skip-maps --skip-bigquery`.
- Copernicus marine forecast download succeeded.
- Retained 3 km Western Mediterranean WRF `d02` input loaded successfully.
- Core route/place artifacts and the staging latest pointer were published.
- BigQuery did not run on the critical publication path.

## Verified staging API results

### Health

`GET /health` returned:

```json
{
  "status": "ok",
  "latest_date": "2026-07-15",
  "latest_run": "2026-07-15T1551Z",
  "storage_backend": "gcs",
  "environment": "test"
}
```

### Briefing

An example route briefing returned HTTP 200 and `application/json`:

```text
GET /routes/marseille_palma/briefing?date=2026-07-15&run=2026-07-15T1551Z
```

Marseille–Palma was only a representative example of the normal API calling pattern. Do not special-case this route.

### Cala Fornells correction

`GET /places/fornells?date=2026-07-15&run=2026-07-15T1551Z` confirms:

- name: `Cala Fornells`
- latitude: `39.5333`
- longitude: `2.4379`
- parent: `palma` (the repository's Mallorca hierarchy root)
- Mallorca observation candidates
- no Menorca observation candidate

Four affected route endpoints, sample paths, descriptions, and captain-exposure notes were updated in commit `b5d5f2c`.

## Blocking staging defect

Do **not** promote the staging image to production yet.

An uncached decision-map request returns HTTP 500:

```text
GET /routes/marseille_palma/artifacts/route_decision_map.png?date=2026-07-15&run=2026-07-15T1551Z
```

Response:

```json
{
  "detail": "On-demand map generation failed: Could not resolve Copernicus forecast outputs in /app/humanintheloop/mvp_data; expected wave and current NetCDF files."
}
```

The publication test intentionally used `--skip-maps`, so no stored map exists. The API then attempted on-demand generation, but the staging service could not resolve the required Copernicus wave/current NetCDF inputs.

### Required map fix

Choose and test one durable approach:

1. Preferred: ensure the publisher uploads canonical Copernicus inputs into the staging bucket and make the API reliably download those objects before on-demand map generation.
2. Alternatively: run map generation as a separate bounded Cloud Run job after core publication and store generated artifacts in the immutable run path.
3. Keep map generation optional. A map failure must return a clear artifact-level error and must never invalidate or roll back a valid core forecast.

Verify both cached and uncached behavior after the fix:

- first request can generate or retrieve inputs and returns `200 image/png`;
- second request returns the stored/cached artifact quickly;
- core `/health`, `/routes`, `/briefing`, and `/places` remain available if map generation fails.

## Implemented reliability changes

Commit `b5d5f2c` contains:

1. The core run manifest and `latest_run.json` are written before optional BigQuery export.
2. Immutable core run files are uploaded before the latest pointer.
3. `--skip-bigquery` was added to `generate_daily_briefing.py`.
4. Preliminary and high-resolution orchestrator publication commands use `--skip-bigquery`.
5. BigQuery REST calls now have a configurable timeout through `PREDSEA_BIGQUERY_HTTP_TIMEOUT_SECONDS` (default 30 seconds).
6. Optional BigQuery diagnostics can be uploaded afterward without changing the core publication contract.
7. Cala Fornells was moved from Menorca to Mallorca with corrected coordinates and route geometry.
8. The definitive architecture plan was added under `docs/`.

## Validation already run

The following passed before commit:

- 84 targeted publication, route, place, SOCIB, and BigQuery tests.
- 11 daily/GCP orchestrator tests.
- Python compilation for the changed publisher, orchestrator, and BigQuery modules.
- Git diff whitespace validation.

One broader `test_run_based_outputs.py` invocation reached 8 passing tests and then blocked in an existing Google API retry path. The directly relevant generator test passed when run explicitly. Do not report that interrupted broad invocation as a full-suite pass.

## Previously fixed ETL/model problems

These were diagnosed and fixed before commit `b5d5f2c`:

1. Recursive place/catalog lookup.
2. Broken `/routes` endpoint behavior.
3. VM zone and machine-type fallback.
4. Whole-VM retry after Spot preemption with forcing reuse.
5. Standard VM final fallback.
6. ECMWF GRIB reference-time/forecast-step normalization.
7. WPS-compatible chronological GRIB splitting/ordering.
8. ECMWF Vtable soil and snow mappings.
9. WPS timestamp and field-inventory validation.
10. Invalid MPI patch decomposition.
11. Invalid 1:1 same-resolution nesting.
12. Valid two-domain operational 3 km topology.
13. Stable WRF timestep/decomposition benchmark.
14. Forecast duration derived from start/end window and bounded by forcing coverage.
15. Circular-reference-safe WRF publication context.
16. Operational `d02` WRF ingestion/publication support.

Relevant recent commits:

- `b5d5f2c` publish forecasts before optional analytics
- `e461429` serialize WRF publication context safely
- `0b0ebe7` derive WRF duration from forecast window
- `2838079` align cloud WRF launch and Copernicus currents
- `77e2c47` use valid two-domain operational WRF topology
- `4bf062e` use safe WRF MPI decomposition

## Immediate next steps

1. Diagnose and fix staging Copernicus input resolution for map generation.
2. Rebuild a new immutable image from a clean commit.
3. Update only `predsea-api-test` and `predsea-publication-test` to that digest.
4. Repeat core publication if required, or run a separate map-enrichment staging job.
5. Verify:
   - staging `/health`;
   - route catalog;
   - representative briefing;
   - Cala Fornells;
   - WRF `d02` lineage;
   - cached and uncached `route_decision_map.png`;
   - no writes to production storage.
6. Inspect the current production `manual_recovery` pointer and ensure promoting an older July 15 run would not regress July 16 data.
7. Only after every staging gate passes, promote the exact tested digest to production service and production job.
8. Verify production and retain the prior Cloud Run revision for rollback.
9. Continue Phase 2 from the definitive plan: durable stage manifests, resumability, and removal of long VM polling from Cloud Run.

## Useful read-only verification commands

The next agent must still run the required `gcloud help` command before each leaf command.

```bash
gcloud run jobs executions describe predsea-publication-test-b7qbf \
  --project=predsea-api \
  --region=europe-west1 \
  --format='json(status.conditions,status.completionTime,status.succeededCount)' \
  --quiet
```

```bash
curl -s https://predsea-api-test-193957983101.europe-west1.run.app/health
```

```bash
curl -s 'https://predsea-api-test-193957983101.europe-west1.run.app/places/fornells?date=2026-07-15&run=2026-07-15T1551Z'
```

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' \
  'https://predsea-api-test-193957983101.europe-west1.run.app/routes/marseille_palma/briefing?date=2026-07-15&run=2026-07-15T1551Z'
```

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type} %{size_download}\n' \
  'https://predsea-api-test-193957983101.europe-west1.run.app/routes/marseille_palma/artifacts/route_decision_map.png?date=2026-07-15&run=2026-07-15T1551Z'
```

## Definitive product direction

The intended complete solution is not merely the staging publisher:

- 3 km Western Mediterranean backbone;
- hourly output;
- target five-day horizon after forcing/runtime validation;
- independent 1 km coastal tiles for high-priority regions, initially 24–48 hours;
- core forecast published first;
- regional refinements published independently;
- maps and BigQuery handled asynchronously;
- durable GCS checkpoints and idempotent stages;
- interruption recovery without repeating downloads or successful WPS/WRF stages.

See [`etl-definitive-solution-plan.md`](./etl-definitive-solution-plan.md) for the full staged architecture, validation gates, rollout gates, and compute policy.
