# PredSea ETL Definitive Solution Plan

Last updated: 2026-07-15
Status: implementation approved and in progress

## Objective

Operate a reliable daily marine-forecast ETL that publishes useful forecasts as soon as they are available, survives infrastructure and optional-service failures, resumes instead of repeating expensive work, and supports a Western Mediterranean 3 km backbone with independent 1 km coastal refinements.

## Current verified state

The atmospheric model itself is no longer the primary blocker.

- ECMWF forcing download and GRIB validation work.
- GRIB forecast-reference metadata and chronological message handling work with WPS `ungrib.exe`.
- The ECMWF Vtable contains the required soil and snow fields.
- WPS geogrid, ungrib, metgrid, and WRF real initialization complete successfully.
- The valid operational topology is two domains at 3 km regional resolution. The former 1:1 same-resolution nests were invalid and have been removed.
- The safe WRF decomposition and timestep configuration have completed a 24-hour simulation.
- The completed WRF output for run `2026-07-15T1551Z` was uploaded to GCS.
- The API is healthy, but the WRF-backed run was not promoted because the monolithic publisher blocked during an optional BigQuery export.
- No compute VM is currently running.

The immediate problem is therefore publication reliability, not atmospheric-model stability.

## Design principles

1. Publish the core forecast before optional enrichment.
2. Store the output and status of every expensive stage durably in GCS.
3. Make every stage idempotent and safe to retry.
4. Derive related configuration values from a single source of truth.
5. Validate structural invariants before allocating an expensive VM.
6. Never let maps, BigQuery, observations, or external APIs block a valid forecast.
7. Stop compute resources deterministically on success and failure.
8. Publish by atomically changing a small `latest` pointer only after core validation passes.

## Phase 1 — Restore a clean operational publication

### Work

1. Cancel the stale publication-only Cloud Run execution.
2. Write the run manifest and core route/place artifacts before BigQuery export.
3. Upload the complete core run directory and then update `latest_run.json`.
4. Add a `--skip-bigquery` publication option for the orchestrated critical path.
5. Add bounded HTTP timeouts to BigQuery operations.
6. Treat BigQuery export, station metadata export, maps, figures, route-cache generation, climatology checks, and model comparisons as retryable optional work.
7. Include the corrected Cala Fornells coordinates, Mallorca hierarchy, route geometry, and operational notes.
8. Run a publication-only recovery for the completed WRF run.
9. Verify the API reports the WRF-backed run as latest and serves its route/place data.

### Exit criteria

- The Cloud Run publication execution reaches terminal success.
- The API `health` response identifies the intended WRF-backed run.
- The run manifest reports `publication_phase=high_resolution` and `wrf_status=complete`.
- Core route snapshots and place weather are readable.
- An unavailable BigQuery export does not prevent any of the above.

## Phase 2 — Resumable staged ETL

The monolithic orchestration will be replaced by explicit stages with durable manifests.

| Stage | Responsibility | Durable success output |
|---|---|---|
| 1 | Select ECMWF/model cycle and forecast window | `run_manifest.json` in `selected` state |
| 2 | Download atmospheric and marine forcing | Versioned forcing objects in GCS |
| 3 | Validate coverage, variables, levels, timeline, and checksums | `forcing_validation.json` |
| 4 | Prepare WPS inputs | Versioned intermediate inputs and WPS config |
| 5 | Select zone/machine and create VM | Attempt record with zone, machine, and provisioning model |
| 6 | Run geogrid, ungrib, metgrid, and real | Per-stage markers, logs, and reusable outputs |
| 7 | Run WRF | Hourly NetCDF outputs and WRF completion marker |
| 8 | Validate forecast completeness and physical sanity | `forecast_validation.json` |
| 9 | Publish core forecast | Immutable run objects followed by atomic latest pointer |
| 10 | Generate maps, figures, and route caches | Independent optional artifact markers |
| 11 | Export analytics and validation to BigQuery | Independent export marker and diagnostics |
| 12 | Finalize and clean up compute | Terminal manifest and stopped/deleted VM record |

### Stage contract

Every stage records:

- state: `pending`, `running`, `succeeded`, `failed`, or `skipped`;
- start and completion timestamps;
- attempt number;
- input object names and checksums;
- output object names and checksums;
- error category and diagnostic location;
- whether retry is safe;
- code/image version.

On restart, the controller reads these records and begins at the first incomplete or invalid stage. It does not redownload forcing or rerun WPS/WRF when validated outputs already exist.

### Orchestration boundary

Cloud Run jobs should execute bounded stages. They should not remain alive for hours polling a Compute Engine VM. VM progress is reported through GCS stage markers and logs. A short controller invocation reconciles state and launches or resumes the next action.

## Phase 3 — Forecast product architecture

### Operational backbone

- Region: Western Mediterranean.
- Resolution: 3 km.
- Temporal output: hourly.
- Target horizon: five days, subject to forcing coverage validation.
- Publication priority: first forecast product online each day.

### Coastal refinement

- Resolution: 1 km.
- Execution: independent regional WRF workloads, not multiple same-resolution nests in one process.
- Initial horizon: 24–48 hours, extended only after measured cost and stability tests.
- Publication: each tile replaces the 3 km data inside its footprint when it passes validation.
- Failure isolation: one tile cannot block the backbone or another tile.

Initial candidate tiles:

1. Balearic Islands.
2. Spanish Mediterranean coast.
3. Southern France and Ligurian coast.
4. Corsica and Sardinia.
5. Western Italian coast.

Tile boundaries will follow maritime demand and coastal exposure rather than the static destination list. Inland destinations must not create or enlarge marine compute domains.

## Preflight validation gates

Before VM creation:

- requested forecast duration equals the configured start/end interval;
- forcing coverage is at least the requested duration;
- expected timestamps and mandatory atmospheric/soil/snow fields exist;
- every active child domain has a supported `parent_grid_ratio` of at least 3;
- domain geometry is contained by its parent;
- MPI decomposition leaves safe patch dimensions for every active domain;
- requested CPUs and machine family fit project quota;
- the selected WRF build supports the requested MPI/OpenMP mode;
- estimated disk capacity covers intermediate and history outputs with margin.

After WPS/real:

- every expected timestamp exists and has a non-trivial field inventory;
- `met_em` and `wrfinput` files contain finite, physically plausible values;
- boundary files cover the entire run window.

During WRF:

- inspect all-rank CFL, NaN/Inf, fatal, and timing signals;
- use a bounded early throughput gate;
- stop unsuitable runs instead of waiting for the overall timeout.

Before publication:

- required hourly files are present and readable;
- temporal coverage and domain metadata match the manifest;
- core route/place JSON is valid;
- immutable run objects are uploaded before changing the latest pointer.

## Retry and compute policy

1. Reuse forcing and WPS outputs after infrastructure failure.
2. Retry VM creation across approved zones.
3. Prefer the largest cost-effective machine that fits quota and measured scaling.
4. Allow smaller machine fallbacks when throughput remains inside the operational window.
5. Spot may be used for retryable stages with durable checkpoints.
6. Use a Standard VM for the final availability-oriented attempt.
7. Record the actual termination reason; never classify every missing marker as preemption.
8. Stop VMs on every terminal branch and retain diagnostics according to a defined policy.

## Publication policy

The customer-visible sequence is:

1. Publish external marine-source preliminary data if the daily WRF run is still pending.
2. Publish the validated 3 km WRF backbone atomically.
3. Add validated 1 km coastal refinements as they complete.
4. Generate maps and presentation artifacts asynchronously.
5. Export BigQuery analytics asynchronously with bounded retries.

The API must expose lineage, resolution, publication phase, WRF status, run ID, and coverage for each product so clients can distinguish preliminary, backbone, and refined results.

## Rollout gates

1. Phase 1 recovery succeeds for the retained completed run.
2. One clean end-to-end 3 km daily run succeeds unattended.
3. Three consecutive daily 3 km runs succeed or resume correctly after injected optional-stage failures.
4. A forced VM interruption proves checkpoint reuse.
5. The five-day 3 km benchmark meets stability, runtime, disk, and cost targets.
6. One 1 km coastal tile passes a controlled benchmark without affecting the live backbone.
7. Additional tiles are introduced one at a time using measured demand and cost.

## Phase 4 — Forecast quality and comparative verification

Forecast quality is an independent, asynchronous ETL. It must never delay the
daily forecast publication, and its tables, reports, credentials, and object
prefixes remain isolated from production serving.

### Evidence layers

| Layer | Required content |
|---|---|
| Forecast archive | Immutable raw PredSea WRF, SWAN, and CROCO samples with run cycle, valid time, lead hour, grid/version, and coordinates |
| Baseline archive | ECMWF atmosphere and Copernicus wave/ocean values sampled at exactly the same coordinates and valid times |
| Observation archive | Quality-controlled buoy, tide-gauge, weather-station, HF-radar, and satellite measurements with provider QC flags |
| Matchups | Reproducible forecast-baseline-observation triples, including distance/time offsets and rejection reasons |
| Scores | Metrics by model, variable, region/tile, station, lead-time band, season, and weather/sea-state regime |

The authoritative comparison is against observations. ECMWF and Copernicus are
competitive baselines, not ground truth. PredSea and each baseline must be
evaluated on the same matched samples; missing data cannot be converted into a
win or silently dropped from only one model.

### Metrics

- scalar fields: bias, MAE, RMSE, correlation, centered RMSE, and sample count;
- wind/current/wave directions: circular bias and circular MAE;
- threshold events: probability of detection, false-alarm ratio, critical
  success index, and Brier score when probabilities exist;
- operational route products: error in peak conditions, threshold-crossing
  timing, best-window agreement, and unsafe false-negative rate;
- coverage: availability, latency, spatial coverage, and rejected-match counts.

Every score is stratified at minimum by lead bands `0–24`, `25–48`, `49–72`,
`73–96`, and `97–120` hours. A five-day aggregate alone is insufficient because
it can hide degradation late in the forecast.

### Anti-leakage and correction policy

1. Preserve raw model values permanently.
2. Compute verification before applying any bias correction.
3. Train corrections only on earlier cycles and evaluate them on later,
   untouched cycles.
4. Version correction models and expose both raw and corrected lineage.
5. Never learn from observations whose valid time was unavailable when the
   forecast was issued.

### Quality gates

Before a new model, horizon, or region can replace an existing product:

1. at least 30 days of automated matchup collection, with an explicit
   low-sample exception for bounded staging experiments;
2. sufficient samples in every customer-critical lead band and sea-state
   regime;
3. no physical-range, continuity, or coastal-mask validation failure;
4. unsafe false negatives do not regress beyond the agreed tolerance;
5. PredSea demonstrates non-inferiority to the current baseline on the primary
   operational metrics, with confidence intervals reported;
6. the result repeats on unattended cycles and is published as a versioned
   quality report.

Staging may expose experimental native forecasts before this gate, clearly
labelled and never used as the production default. Promotion is an explicit
decision based on the report, not an automatic consequence of a successful
model run.

### Implementation sequence

1. Correct the current comparison specification so CROCO, NEMO, and SWAN
   providers are unambiguous; remove the stale `predsea_roms` path.
2. Replace the exact station-ID bias join with the same spatial/temporal matchup
   algorithm used by the real comparison path.
3. Ingest real ECMWF and Copernicus baseline rows rather than merely naming
   baseline providers in configuration.
4. Materialize versioned `forecast_samples`, `observation_samples`,
   `matchups`, and `verification_scores` tables in the staging BigQuery
   dataset, partitioned by valid date and clustered by model, variable, region,
   and lead hour.
5. Generate immutable daily and rolling 7/30-day quality reports in the staging
   bucket.
6. Add a read-only staging API endpoint for coverage and score inspection.
7. Promote only the evaluation schema and jobs after staging proves that they
   cannot block or modify forecast publication.

Observation providers are registered in
`simulation/quality/observation_registry.json`, validated against the versioned
schema beside it. Catalog-based networks can add newly discovered stations
without a code release. A genuinely new provider requires only a connector plus
one registry entry and its normalization/QC tests; it does not require changes
to WRF, SWAN, CROCO, forecast domains, or production publication.

## Immediate implementation order

1. Complete Phase 1 and promote the retained WRF output.
2. Introduce the stage-manifest schema and atomic publication helper.
3. Split optional publication/enrichment from the critical path.
4. Replace VM polling with state reconciliation.
5. Prove resumability with an interrupted test run.
6. Extend the 3 km forcing and WRF window to five days and benchmark it.
7. Design and benchmark the first independent 1 km coastal tile while the 3 km service remains live.
8. Run comparative verification continuously from the first staging forecasts;
   quality data collection proceeds in parallel with horizon and region
   expansion.
