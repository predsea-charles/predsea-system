# PredSea Forecast Architecture — Autonomous Agent Master Handoff

Last updated: 2026-07-16 14:40 Europe/Madrid  
Repository: `predsea-system`  
Google Cloud project: `predsea-api`  
Primary region: `europe-west1`

## 1. Mission

Complete the PredSea forecast architecture through:

1. a validated, repeatable 3 km multi-day Mediterranean atmospheric backbone;
2. independent validated 1 km five-day coastal forecasts;
3. PredSea-owned wave and ocean forecasts, rather than republishing Copernicus
   as the final product;
4. a reusable multi-region expansion framework;
5. objective quality evaluation against observations and external forecast
   baselines; and
6. safe staging validation before any production promotion.

The live production API and current operational ETL must remain available while
this work is developed. A staging success is not permission to modify
production. Production promotion requires the explicit gates in this document.

## 2. User intent and operating authority

The user wants an autonomous implementation. Do not repeatedly ask for routine
technical decisions. Make evidence-based decisions, implement, test, document,
commit, push, deploy to staging, run, and inspect results.

Autonomy does **not** broaden the production safety boundary:

- do not break or replace the production API;
- do not modify the production `daily-orchestrator`;
- do not modify the production Scheduler trigger;
- do not update production `latest` pointers;
- do not publish experimental outputs as customer-ready forecasts;
- do not claim a forecast exists unless the native numerical model actually
  completed and its output passed content validation.

## 3. Authoritative working copy

Use this clean worktree:

```text
/private/tmp/predsea-etl-release
```

Branch:

```text
codex/wrf-curvilinear-publication
```

Do not deploy from the user's main workspace. It contains unrelated local
changes which belong to the user.

Recent relevant commits:

```text
9641e7d feat: add forecast quality staging framework
c7e7b75 fix: generate valid SWAN output command
6799288 feat: add native marine staging foundation
```

Commit `9641e7d` has been pushed to origin.

At the time this handoff was written, the following changes were still
uncommitted in the clean worktree:

```text
docs/native-marine-forecast-plan.md
simulation/marine/croco/
scripts/validate_native_marine_output.py
tests/test_validate_native_marine_output.py
```

Inspect `git status --short` before editing. Preserve any changes already
present.

## 4. Mandatory Google Cloud command discipline

Before **every** `gcloud` command:

1. read:

   ```text
   .agents/skills/gcloud/SKILL.md
   ```

2. run `gcloud help` for the exact leaf command;
3. run one `gcloud` command at a time;
4. use explicit `--project=predsea-api`;
5. use explicit `--region=europe-west1` or the exact zone;
6. use `--quiet`;
7. reduce output with `--format`, filters, and limits;
8. do not chain shell operations into a `gcloud` command.

Do not expose environment variables or secrets in logs or documentation.
Credentials previously printed in terminal history must be treated as
compromised and rotated separately; never copy them into commits.

## 5. What production currently is

The existing production customer path is the Cloud Run API and the existing
daily ETL. It must remain available during this project.

Production currently has a lower-resolution operational path. It should be
treated as the fallback until the replacement architecture is proven through an
unattended repeatable run.

The staging publication/API work has already demonstrated that:

- route briefings can be published as structured JSON;
- the Relay/WhatsApp-facing response path works;
- Cala Fornells is correctly represented in Mallorca at approximately
  `39.5333, 2.4379`;
- BigQuery publication can be non-blocking;
- publication can be decoupled from the expensive simulation;
- an immutable staging release can be tested without moving production.

This does **not** prove the complete fresh numerical-model-to-API chain.

## 6. Target architecture

```text
ECMWF atmosphere forcing
        |
        v
3 km WRF multi-day Mediterranean backbone
        |
        +--------------------------+
        |                          |
        v                          v
1 km coastal WRF nests       Regional marine forcing preparation
                                   |
                          +--------+--------+
                          |                 |
                          v                 v
                     SWAN waves       CROCO ocean
                          |                 |
                          +--------+--------+
                                   |
                         Canonical PredSea NetCDF
                                   |
                     Content validation and lineage
                                   |
                 Observation/external-model quality matchups
                                   |
                        Immutable staging run bundle
                                   |
                         Staging API and route products
                                   |
                       Guarded atomic production promotion
```

### Provider roles

- **ECMWF** supplies atmospheric forcing for WRF and wind forcing for SWAN/CROCO.
- **Copernicus Marine** supplies initial and open-boundary marine conditions,
  and remains an independent comparison/fallback source.
- **PredSea WRF/SWAN/CROCO** must be the final native forecast providers.
- **Observations** are ground truth where quality-controlled measurements exist.

Copernicus is not “the PredSea forecast.” It may initialize and constrain the
boundaries of PredSea's models in the same way ECMWF constrains WRF.

## 7. Product ladder

Develop versions in this order, keeping the current live solution available:

| Version | Atmosphere | Waves | Ocean | Forecast horizon | Publication |
|---|---|---|---|---|---|
| A | 3 km WRF | Copernicus fallback | Copernicus fallback | 24 h | Existing production fallback |
| B | 3 km WRF | Copernicus fallback | Copernicus fallback | 96–120 h | Staging, then production if proven |
| C | 3 km backbone + independent 1 km coastal WRF | Native 1 km SWAN | Copernicus fallback | 120 h target | Staging |
| D | Same | Native 1 km SWAN | Native 1 km CROCO | 120 h target | Staging |
| E | Repeatable multi-region profiles | Native regional SWAN | Native regional CROCO | Region-specific | Staging then guarded production |

If five days cannot fit the operational window with adequate margin, test a
four-day horizon rather than silently exceeding timeouts. Preserve full hourly
publication where practical; reducing published time frequency does not reduce
the cost of internal numerical integration unless model I/O is the bottleneck.

## 8. Atmospheric work already proven

Important WRF/WPS findings and fixes:

- ECMWF GRIB metadata and WPS message ordering were diagnosed and corrected.
- GRIB messages must be ordered chronologically across pressure and surface
  fields.
- Soil/snow Vtable mappings must be validated by field inventory, not process
  exit code.
- WRF's former seven-domain emergency configuration became invalid when several
  children were changed to the same 3 km resolution as their parent:
  `parent_grid_ratio=1` is structurally invalid for these nests.
- The stable emergency topology is two domains, not seven redundant
  same-resolution nests.
- MPI decomposition must preserve minimum patch dimensions.
- The 45-second configuration and later conservative timestep tests showed that
  the immediate instability came from the invalid 1:1 nest geometry, not merely
  timestep magnitude.
- WRF completed a real integration substantially beyond the ten-minute gate.
- A later failure was caused by `run_hours` disagreeing with `end_date` and
  boundary coverage, not by failed WRF physics.

Required permanent preflight invariants:

1. derive duration from `start_date` and `end_date`;
2. verify forcing covers the entire requested duration;
3. require `parent_grid_ratio >= 3` for every active child domain;
4. reject domain decompositions below safe patch dimensions;
5. verify all WPS timestamps and mandatory fields;
6. size disk from measured per-timestep output plus intermediates and margin;
7. configure timeout from measured runtime with margin, never from wishful ETA.

## 9. Native SWAN status

### Reproducible image

Pinned image:

```text
europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/swan@sha256:50c5d25f818e742bb57bf9c73a3849acd8f16de73e53c3c92d015d332d5980e3
```

Source is pinned in:

```text
simulation/marine/swan/Dockerfile
```

SWAN version: 41.51.

### Configuration evidence

- The Balearic coastal grid is approximately 1 km.
- Native run uses ECMWF 10 m winds.
- Hourly Copernicus wave parameters are converted into explicit parametric
  JONSWAP conditions on open boundaries.
- SWAN is the numerical forecast; Copernicus is boundary forcing.
- A ten-minute computational step failed SWAN's geographic higher-order
  propagation CFL check.
- A five-minute internal step is stable enough for the bounded benchmark.
- Publication remains hourly.
- Parallel native output is VTK because SWAN's MPI NetCDF collector failed while
  merging otherwise-created rank outputs.

### Active benchmark at handoff

Cloud Build:

```text
4060bb95-b645-4ca1-909f-2b5d6b0ca4d6
```

At 2026-07-16 14:40 Europe/Madrid it was `WORKING`.

It is a bounded six-hour Balearic 1 km benchmark on `E2_HIGHCPU_8`. Expected
native timestamps: seven, including hour zero.

Expected staging artifact prefix:

```text
gs://predsea-daily-outputs/staging/native-marine/swan/2026-07-16/4060bb95-b645-4ca1-909f-2b5d6b0ca4d6/
```

Temporary submitted package:

```text
/private/tmp/predsea-swan-balearic-1km-6h
```

### Immediate SWAN next actions

1. Poll the build to terminal state.
2. If successful, list and download the immutable staging artifacts.
3. Verify:
   - normal SWAN termination;
   - seven PVD timestamps;
   - all referenced VTK pieces exist;
   - actual fields include `HSIGN`, peak period, direction, wind, and depth;
   - fields are finite and within physical limits;
   - geographic coverage matches the versioned region.
4. Implement deterministic parallel-VTK-to-canonical-NetCDF conversion.
5. Run `scripts/validate_native_marine_output.py`.
6. Run `scripts/swan_forecast_ingestor.py --dry-run` on the canonical file.
7. Store benchmark runtime, disk, image digest, input hashes, and validation
   report.
8. Only then run a 24-hour benchmark.
9. Project 96 h and 120 h runtime/storage/cost from measured throughput.
10. Run the longest horizon that fits the operational window with margin.

Do not label the current six-hour benchmark as a five-day forecast.

## 10. Native CROCO status

### Reproducible source

CROCO version: 2.1.3.

Official archive checksum:

```text
4b7464365f3e6197ed83b5ae8842cc1efc736add2c86e16a0ff188e7650661c1
```

Files:

```text
simulation/marine/croco/Dockerfile
simulation/marine/croco/cloudbuild.yaml
simulation/marine/croco/smoke_basin.sh
```

The image compiles the official analytic BASIN configuration. This is only a
compiler, MPI/NetCDF-linkage, initialization, integration, and output smoke
test. It is not a Balearic forecast.

### Failures already resolved

1. First build failed because CROCO's build scripts call `python3`; it was
   missing from the builder. `python3` has been added.
2. The image then compiled successfully, but the smoke run reported:

   ```text
   READ_INP ERROR: Cannot find input file ''.
   ```

   CROCO v2.1.3 expects its configuration filename as a positional argument,
   not via stdin. The script was changed from:

   ```text
   croco < croco.in
   ```

   to:

   ```text
   croco croco.in
   ```

3. The smoke script now prints stdout, stderr, and `/work` contents on failure,
   so future failures are diagnosable.

### Active CROCO build at handoff

Cloud Build:

```text
20866267-97ee-47cb-abbc-87676e83b359
```

At 2026-07-16 14:40 Europe/Madrid it was `WORKING`.

### Immediate CROCO next actions

1. Poll build `20866267-97ee-47cb-abbc-87676e83b359`.
2. If it fails, read the bottom of the build log and fix only the evidenced
   cause.
3. If it succeeds:
   - record the immutable image digest;
   - commit the pinned image/smoke files;
   - push the branch.
4. Build the versioned Balearic CROCO configuration:
   - approximately 1 km horizontal grid;
   - 30 terrain-following vertical levels;
   - validated bathymetry and land mask;
   - Copernicus 3D temperature, salinity, currents, and sea-level initial state;
   - complete open-boundary conditions;
   - WRF wind, pressure, heat, and freshwater surface forcing;
   - tides where needed for coastal skill.
5. Validate every forcing file independently before spending on integration.
6. Compile the regional executable from the same pinned source.
7. Run six-hour, then 24-hour benchmarks.
8. Project 96/120-hour runtime, storage, and cost.
9. Publish only after native NetCDF passes content and lineage validation.

Do not use only a surface-current Copernicus file and claim it is sufficient
for CROCO. CROCO needs a three-dimensional ocean state and boundaries.

## 11. Canonical native marine format

Native model output must be transformed into versioned canonical PredSea
NetCDF files before ingestion or API publication.

### SWAN canonical variables

Minimum:

```text
time
latitude
longitude
hs       significant wave height, metres
tps      peak wave period, seconds
dir      wave direction, degrees
```

Recommended global attributes:

```text
schema_version = predsea.native_marine.v1
provider = predsea_swan
model_version
region_id
region_version
run_id
cycle_time
forecast_horizon_hours
horizontal_resolution_km
forcing_atmosphere = ECMWF or PredSea WRF
forcing_open_boundary = Copernicus Marine
source_image_digest
source_commit
```

### CROCO canonical variables

Minimum:

```text
ocean_time
lat_rho
lon_rho
zeta
temp
salt
u
v
```

Add derived canonical surface variables for product/API use:

```text
sea_surface_temperature
sea_surface_height
eastward_sea_water_velocity
northward_sea_water_velocity
current_speed
current_direction
```

Never overwrite raw native output. Store:

```text
native/
canonical/
validation/
quality/
manifest.json
```

inside each immutable staging run prefix.

## 12. Native output validator

The authoritative, region-driven validator is:

```text
scripts/validate_marine_output.py
tests/test_validate_marine_output.py
```

It checks:

- exact timestamp count;
- required coordinates;
- optional expected bounding-box coverage;
- required variables;
- finite fraction, defaulting to at least 90%;
- model-specific physical ranges;
- machine-readable pass/fail report.

Before publication:

1. run its tests and the SWAN/CROCO ingestor tests;
2. inspect real native outputs and adjust variable aliases only from evidence;
3. keep the validator strict enough to prevent silent partial publication.

Do not introduce a second generic marine-output validator. One authoritative
region profile and validation implementation prevents rule drift.

The validator must fail closed. A process exit code or file existence is not
proof of a scientifically usable forecast.

## 13. Observation and quality infrastructure

Committed and pushed:

```text
simulation/quality/observation_registry.json
simulation/quality/observation_registry.schema.json
scripts/validate_observation_registry.py
tests/test_validate_observation_registry.py
```

The registry currently describes Puertos del Estado, EMODnet, and SOCIB source
families.

### Adding future observation locations

- Existing catalog-discovered provider: add/activate registry metadata; no
  release should be necessary if discovery is data-driven.
- New provider: add a connector, registry entry, schema validation, quality
  flags, and tests.

Every observation record should carry:

```text
provider
station_id
latitude
longitude
variable
observed_at
value
unit
quality_flag
retrieved_at
source_version
```

### Forecast matchup identity

Every forecast sample must carry:

```text
model
model_version
run_id
cycle_time
valid_time
lead_hour
region_id
region_version
latitude
longitude
variable
raw_value
forcing_lineage
```

Match observations and forecasts by:

- variable;
- valid time within a defined tolerance;
- nearest valid wet model cell within a configured distance;
- region/version;
- forecast lead hour.

### Metrics

Report at least:

- count and observation coverage;
- bias;
- MAE;
- RMSE;
- correlation where sample size permits;
- circular error for directions;
- peak error;
- peak-timing error;
- best-window agreement;
- unsafe false-negative rate;
- metrics by lead-time band, station, region, season, and sea-state regime.

Compare PredSea and Copernicus on **identical matched samples**. Do not claim
one model wins when sample populations differ.

Raw model output must be evaluated before bias correction. Bias correction must
be trained on earlier cycles and evaluated on later untouched cycles.

Missing observations must produce an explicit `insufficient_coverage` result,
never synthetic data or a fabricated score.

## 14. Staging storage and publication layout

Recommended immutable layout:

```text
staging/
  forecasts/
    <region_id>/
      <model>/
        <cycle_time>/
          <run_id>/
            native/
            canonical/
            validation/
            quality/
            manifest.json
```

Staging pointers may reference only bundles that passed all gates. A pointer
update must be atomic and reversible.

Production must continue to use its existing objects/pointers until an explicit
promotion decision.

## 15. Staging API expectations

The staging API must expose the same route/place semantics as production while
allowing an explicit run/model/version selection.

Recommended capabilities:

```text
GET /health
GET /forecast-runs
GET /places
GET /places/{place_id}/forecast
GET /routes/{route_id}/briefing
GET /routes/{route_id}/artifacts/route_decision_map.png
GET /quality/summary
```

Responses should disclose:

- native model/provider;
- resolution;
- horizon;
- cycle and valid time;
- run ID;
- region/version;
- forcing lineage;
- whether the value is native, fallback, or unavailable;
- validation/quality status.

Do not silently serve Copernicus while labeling it PredSea. If native output is
unavailable, return a clearly marked fallback or an unavailable response.

Relay/WhatsApp consumes structured API data and text. The deprecated
briefing-generated WhatsApp-like image, LinkedIn-like image, and briefing map
are not core products and should not block the ETL.

## 16. Multi-region design

Regions must be data/configuration, not hardcoded branches.

Each versioned region profile should define:

```text
region_id
region_version
bbox/polygon
projection
atmosphere_backbone_domain
coastal_atmosphere_nests
swan_grid
croco_grid
bathymetry_version
land_mask_version
open_boundaries
forcing_sources
observation_sources
forecast_horizon
publication_interval
compute_profile
validation_thresholds
```

The same orchestration code should accept a region profile and create an
independent immutable run.

To prove reusability, complete a second-region dry-run or bounded benchmark
without adding region-specific code paths. A Mediterranean region in Italy or
France is appropriate because customers operate along those coasts.

Vessel routes may cross regional boundaries. The API/publication layer must:

- identify all forecast regions intersecting a route;
- select the finest validated native product at each route point;
- fall back explicitly where native coverage is absent;
- preserve provider/resolution provenance per segment.

## 17. Cost and operational strategy

Use measured benchmark evidence, not theoretical assumptions.

For each model/horizon record:

- machine type;
- provisioning model: Spot or standard;
- vCPU and memory;
- wall time;
- simulated time;
- acceleration factor;
- peak disk;
- output size;
- compute price at execution time;
- measured compute cost;
- separately identified storage/network cost.

Recommended policy:

1. Spot for resumable preparation and early model attempts.
2. Persist expensive downloaded/prepared inputs and checkpoints.
3. Retry across approved zones.
4. Fall back to smaller machine types if quota/capacity requires it.
5. Use standard non-Spot capacity as the final operational fallback where
   latency matters more than lowest cost.
6. Do not rerun completed deterministic stages after preemption.

The fastest customer-available forecast should be published atomically by
stage. Publication failure must not force the expensive simulation to rerun.

## 18. Test and promotion gates

### Model run validity

- exact expected timestamps;
- required fields;
- at least 90% finite unless a stricter per-variable threshold is configured;
- physical ranges;
- full configured geographic coverage;
- no fatal/CFL/NaN errors;
- complete forcing lineage;
- measured runtime/disk/cost.

### Pipeline validity

- model discovery rejects `met_em` and other intermediate files;
- ingestors select actual model output by filename and content;
- canonicalization is deterministic;
- publication is resumable;
- BigQuery failure is non-blocking where designed;
- maps, route values, and structured JSON use the same selected run;
- no production pointer changes during staging.

### Quality validity

- real observations only;
- independent Copernicus baseline;
- identical matchup population;
- explicit insufficient sample coverage;
- no synthetic scores;
- no unsupported “PredSea beats Copernicus” claim.

### Production promotion

Production promotion requires all of:

1. staging native numerical run passes;
2. canonical data passes content validation;
3. API route/place values and maps are correct;
4. Relay-facing data contain real values, not `None`;
5. an unattended repeat run succeeds;
6. fallback remains available;
7. immutable image digests and commit are recorded;
8. atomic pointer/revision update has a tested rollback;
9. production smoke checks pass after promotion.

## 19. Recommended execution sequence from this handoff

### Phase 1 — close active cloud experiments

1. Poll SWAN build `4060bb95-b645-4ca1-909f-2b5d6b0ca4d6`.
2. Poll CROCO build `20866267-97ee-47cb-abbc-87676e83b359`.
3. Download and validate successful artifacts.
4. Preserve diagnostics for any failure.
5. Commit and push CROCO smoke work only after it passes.

### Phase 2 — canonical SWAN product

1. Inspect real VTK/PVD schema.
2. Implement deterministic conversion.
3. Add unit and integration fixtures from a small real output subset.
4. Run native output validator.
5. Run SWAN ingestor dry-run.
6. Archive manifest and benchmark.

### Phase 3 — longer SWAN horizons

1. Run 24 h.
2. Calculate sustained throughput from the full run, not only startup.
3. Size 96/120 h disk/runtime.
4. Run 120 h if it fits with margin; otherwise run 96 h and record why.
5. Validate all hourly timestamps and route/place sampling.

### Phase 4 — regional CROCO

1. Build grid and vertical coordinates.
2. Prepare full 3D initial/boundary state and surface forcing.
3. Validate inputs.
4. Compile pinned regional executable.
5. Run 6 h, 24 h, then projected 96/120 h.
6. Validate canonical output and ingestion.

### Phase 5 — quality archive

1. Implement normalized observation ingestion from registry.
2. Implement forecast sample archive.
3. Implement spatial/temporal matchups.
4. Compute metrics against observations and Copernicus.
5. Publish staging quality summary.

### Phase 6 — 3 km multi-day backbone

1. Confirm full forcing timestamp coverage.
2. Run a fresh 3 km 96/120 h WRF staging cycle.
3. Validate all outputs and cost.
4. Publish atmosphere-only staging products.
5. Repeat unattended.

### Phase 7 — independent 1 km five-day coastal system

1. Create valid 3:1 WRF coastal nests from the 3 km backbone.
2. Benchmark each coastal region independently.
3. Drive SWAN and CROCO from validated regional forcing.
4. Prove five-day output or formally select a four-day operational fallback.
5. Keep 3 km backbone available even if one coastal region fails.

### Phase 8 — multi-region proof

1. Add a second region entirely through a region profile.
2. Run preflight and bounded model tests.
3. Publish staging endpoints.
4. Test a route that moves between regions.
5. Document onboarding steps and measured incremental cost.

### Phase 9 — guarded production promotion

Only after every relevant gate passes and an unattended repeat succeeds.

## 20. Evidence required to call the project complete

Do not close this project based on plans or unit tests alone. The following
artifacts must exist and be inspected:

- successful fresh 3 km multi-day WRF run;
- successful independent 1 km five-day coastal WRF run, or a user-approved
  four-day operational horizon backed by measured constraints;
- successful native five-day SWAN output for at least one coastal region;
- successful native five-day CROCO output for at least one coastal region;
- canonical validated NetCDF bundles for all models;
- staging API serving those native bundles with correct lineage;
- real observation matchup reports;
- independent Copernicus comparison on identical samples;
- unattended repeat success;
- second-region proof without code branching;
- production unchanged until explicit guarded promotion;
- tested rollback and fallback after promotion.

Anything less is progress, not completion.

## 21. Important documentation to read

Read these before making architectural changes:

```text
docs/etl-definitive-solution-plan.md
docs/native-marine-forecast-plan.md
docs/etl-agent-handoff-2026-07-16.md
docs/real-validation-runbook.md
docs/prediction-etl.md
docs/api-whatsapp.md
simulation/quality/observation_registry.json
simulation/quality/observation_registry.schema.json
```

Also inspect current code rather than trusting documentation when they differ.
Runtime evidence and the current worktree are authoritative.

## 22. First commands for the next agent

Run locally:

```bash
cd /private/tmp/predsea-etl-release
git status --short
git log -5 --oneline
```

Then follow the mandatory gcloud skill and inspect the two active builds.

After cloud state is known, continue from Phase 1 above. Do not restart already
successful expensive stages merely to simplify the workflow.
