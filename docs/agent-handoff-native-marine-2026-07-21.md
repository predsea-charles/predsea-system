# PredSea Native Marine Forecast — Agent Handoff

Last updated: **2026-07-22 20:05 Europe/Madrid**
Repository: `/Users/charles.santana/PredSea/predsea-system`  
Google Cloud project: `predsea-api`  
Primary GCP location: `europe-west1`  
Development branch pushed to origin: `codex/wrf-curvilinear-publication`

This is the authoritative operational handoff for continuing the native PredSea
marine forecast project. Read it before changing code or cloud resources. Older
handoffs remain useful history, but their run IDs, digests, and status may be
stale.

## 0. Read this first: exact current state

The active objective is a native, hourly, 1 km Western Mediterranean marine
forecast produced by PredSea in GCP. Geographic coverage has priority over
extending the horizon to 96/120 hours. API publication comes only after every
regional tile has passed its model gates.

The current work is **not production**. It is isolated in
`gs://predsea-daily-outputs-test`. Production services, jobs, scheduler, IAM,
bucket and `latest` pointers have not been changed and must remain untouched.

### Current gate table

| # | Gate | State | Evidence / next action |
|---:|---|:---:|---|
| 1 | Staging isolation and immutable run layout | ✅ | GCP Batch plus staging bucket; no production writes |
| 2 | Balearic 1 km CROCO grid | ✅ | 501 x 401 rho grid, 32 levels, wet fraction 0.9289, rx0 <= 0.2 |
| 3 | Real 3-D CMEMS ocean forcing | ✅ | u/v, temperature, salinity and SSH prepared on the exact grid |
| 4 | Real hourly WRF atmospheric forcing | ✅ | seven exact timestamps for the bounded six-hour test |
| 5 | Grid/forcing/binary dimension and geographic agreement | ✅ | fail-closed checks pass |
| 6 | CROCO climatology time-axis contract | ✅ | `ssh_time`, `uclm_time`, `tclm_time`, `sclm_time` read by CROCO |
| 7 | CROCO SSH variable contract | ✅ | SSH forcing read at model hours 0 and 1 |
| 8 | CROCO incoming longwave contract | ✅ | `radlw_in` read at model hours 0 and 1 |
| 9 | CROCO MPI startup and initial history record | ✅ | Standard `c2d-highcpu-16`, 16 MPI ranks, finite plausible initial fields |
| 10 | Balearic SWAN 1 km / 24 h | ✅ | 25 hourly native-wave timestamps validated in staging |
| 11 | Balearic CROCO six-hour numerical stability | ❌ active blocker | dt=60 s reproduced a STEP2D blow-up; dt=20 s attempt also exited 1, but its model log was not retained |
| 12 | Durable failure diagnostics | 🟡 being implemented | capture CROCO stdout and upload `FAILURE.txt`, log and partial artifacts to run-scoped GCS before rethrowing |
| 13 | Balearic CROCO 24 h | ⬜ | only after a clean six-hour run with seven valid timestamps |
| 14 | Alboran/Gibraltar 1 km | ⬜ | must prove open boundaries, bathymetry, tides/exchange flow and overlap |
| 15 | Gulf of Lion 1 km | ⬜ | independent grid, six-hour gate, then 24-hour gate |
| 16 | Tyrrhenian 1 km | ⬜ | independent grid, six-hour gate, then 24-hour gate |
| 17 | Algerian Basin 1 km | ⬜ | independent grid, six-hour gate, then 24-hour gate |
| 18 | Cross-tile overlap/continuity validation | ⬜ | no gaps, jumps, duplicate authority or mismatched timestamps |
| 19 | Staging API and route-product tests | ⬜ | intentionally after geographic coverage |
| 20 | 96/120-hour forecasts | ⬜ | intentionally after all-region 24-hour proof |
| 21 | Production promotion | ⬜ | requires explicit guarded release decision |

### Latest exact cloud attempt

```text
Cloud Build: 6e3fa9de-aff9-4635-969e-d7a7caedc1d1 (SUCCESS)
Image digest: sha256:ae0fcf8ccdac53963043a31ffb3af34ada78315b2504caf8ca62a632251e528b
Batch job: predsea-sim-balearic-1km-croco-f4323874
Run ID: 2026-07-16T0000Z-croco-balearic-6h-v7
Machine: c2d-highcpu-16 STANDARD, 16 vCPU, 32 GiB, 16 MPI ranks
CROCO timestep: 20 seconds
Forecast gate: 6 hours, expected 7 hourly records
Started: 2026-07-22T17:33:25Z
Failed: 2026-07-22T17:45:17Z
Batch evidence: task 0 exit code 1
Root cause: NOT YET PROVEN because the application stdout was not persisted
```

Do not infer that dt=20 s is numerically unstable from the Batch exit code
alone. The run may have failed during forcing, MPI, integration, validation or
upload. The next run must persist evidence before any new model/configuration
change is considered.

### Work currently in the workspace

`scripts/run_marine_simulation.py` has an uncommitted diagnostic change that:

1. tees CROCO MPI stdout to `croco.stdout.log` while still streaming it;
2. creates a structured `FAILURE.txt` on any CROCO exception;
3. uploads the run-scoped CROCO work directory to
   `predictions/<date>/runs/<run-id>/<region>/failure-diagnostics/`;
4. rethrows the original error so GCP Batch still fails closed.

This change must receive focused tests before commit. Do not accidentally stage
the many unrelated changes in the dirty worktree. The user intentionally
removed large local shapefiles and NetCDF files; do not restore or commit those
deletions as part of this task.

### Immediate continuation sequence

1. Add unit tests for log teeing and best-effort run-scoped failure upload.
2. Run focused marine Batch tests and `git diff --check`.
3. Stage only the diagnostic runner, its tests and this handoff.
4. Commit and push to `codex/wrf-curvilinear-publication`.
5. Build the CROCO Batch image and obtain its immutable digest.
6. Dry-run the same six-hour submission using a new run ID.
7. Submit on `c2d-highcpu-16` STANDARD with 16 MPI ranks and dt=20 s.
8. If it fails, read `FAILURE.txt`, `croco.stdout.log` and partial NetCDF from
   the run-scoped diagnostic prefix before changing anything.
9. If it succeeds, verify exactly seven distinct hourly records, finite values,
   physical ranges, exact geographic coverage and provenance; then run 24 h.

## 1. Mission

Build a reliable, repeatable forecast system in which PredSea runs its own
numerical models:

```text
ECMWF atmosphere forcing
        |
        +--> WPS/WRF --> PredSea atmospheric forecast
        |
        +--> SWAN wind forcing

Copernicus Marine wave boundary conditions --> SWAN --> PredSea wave forecast
Copernicus Marine ocean initial/boundary data --> CROCO --> PredSea ocean forecast

PredSea WRF + SWAN + CROCO
        --> validated canonical NetCDF
        --> immutable staging bundle
        --> staging API / Relay products
        --> guarded production promotion
```

Provider terminology is important:

- ECMWF is forcing for WRF and SWAN. It is not a PredSea marine forecast.
- Copernicus Marine is initial/open-boundary forcing, comparison baseline, and
  fallback. It is not the native PredSea output.
- SWAN output computed by PredSea is the native PredSea wave forecast.
- CROCO output computed by PredSea will be the native PredSea ocean forecast.
- Observations are ground truth where quality-controlled observations exist.

## 2. Non-negotiable safety boundary

Current native marine work is **staging only**.

Do not modify any of the following until explicit production promotion gates
pass:

- production Cloud Run service `predsea-api`;
- production Cloud Run job `daily-orchestrator`;
- production scheduler;
- production bucket `predsea-daily-outputs`;
- production `latest` pointers;
- production traffic or IAM.

The native marine staging bucket is:

```text
gs://predsea-daily-outputs-test
```

A successful model run is not automatic permission to promote. A staging
success must first pass output-content, lineage, API, repeatability, runtime,
disk, and cost gates.

Never:

- print, document, or commit credential values;
- copy `.env` files into build contexts;
- report a forecast as successful because a process returned zero;
- call Copernicus data a PredSea native forecast;
- update a customer-visible pointer before immutable artifacts validate;
- infer that a missing success marker means preemption;
- delete diagnostic or cloud resources without authorization;
- deploy from an unreviewed dirty workspace;
- mix staging and production buckets, services, datasets, or run IDs.

Some credentials were previously exposed in terminal output. Treat them as
compromised and rotate them as a separate security task. Do not repeat their
values in issues, commits, logs, or agent messages.

## 3. Repository operating constraints

The main workspace contains many unrelated user modifications and untracked
files. Preserve them. Stage only files intentionally changed for the current
task.

At this handoff the worktree is on a detached `HEAD`, while commits are pushed
explicitly to:

```text
origin/codex/wrf-curvilinear-publication
```

Recent relevant commits, newest first:

```text
03aacfc fix: emit CROCO climatology time axes
bf7403c feat: enforce regional CROCO grid contracts
7272409 fix: emit CROCO physical grid extents
6e93144 fix: expose Batch vCPUs as CROCO MPI slots
2663435 fix: decode WRF fixed-width timestamps for CROCO
5db44a5 fix: include CROCO interpolation runtime
97ec834 fix: use available CROCO build worker
b6a662b feat: add fail-closed CROCO Batch staging path
8648790 feat: support reproducible Batch resource benchmarks
5f952f9 fix: pin matching currents for native wave publication
8aac7e6 feat: publish native SWAN waves in staging
```

Before editing:

1. read repository `AGENTS.md`;
2. inspect `git status --short --branch`;
3. inspect the relevant files and tests;
4. preserve unrelated changes;
5. use `apply_patch` for edits;
6. run focused tests and `git diff --check`;
7. stage only explicit paths;
8. commit with a narrow message;
9. push detached commits with:

   ```bash
   git push origin HEAD:codex/wrf-curvilinear-publication
   ```

Do not use `git reset --hard`, `git checkout --`, broad cleanup commands, or
bulk staging.

## 4. Mandatory GCP command discipline

Before **every** `gcloud` command:

1. read `.agents/skills/gcloud/SKILL.md` completely;
2. run `gcloud help <exact leaf command>`;
3. execute one `gcloud` command at a time;
4. provide `--project=predsea-api` explicitly;
5. provide `--region=europe-west1`, `--location=europe-west1`, or an exact zone;
6. provide `--quiet`;
7. reduce output using `--format`, filters, freshness, and limits;
8. do not use pipes, redirection, shell substitution, or chained gcloud calls.

Dry-run any state-changing command when supported. Pin deployed Batch images by
immutable digest, never only by tag.

For Batch application logs, the useful resource is:

```text
resource.type="batch.googleapis.com/Job"
```

The `resource.labels.job_id` value observed in logging is the Batch **UID**, not
always the friendly job name. Obtain it from `gcloud batch jobs describe`.

## 5. Current cloud and component state

The authoritative status at this update is:

| Component | Configuration | Evidence/status | Next gate |
|---|---|---|---|
| ECMWF forcing | atmospheric inputs | proven acquisition and validation | reuse per run |
| WRF | Western Mediterranean, 3 km, 24 h | stable native atmospheric forecast proven | provide atmospheric forcing to marine tiles |
| Balearic CROCO grid | bbox 0.5–5.5 E, 37.5–41.5 N; 501 x 401; 32 levels | validated exact bbox, shape, wet fraction 0.9289 and max rx0 0.2 | retained immutable grid |
| Balearic SWAN | 1 km nominal, 24 h, 25 hourly timestamps | staging native wave run validated | replicate only after regional grid preflight |
| Balearic CROCO forcing | CMEMS 3-D u/v, temperature, salinity, SSH plus seven WRF surface timestamps for 6 h | forcing preparation passed | rerun CROCO binary |
| Balearic CROCO | 1 km nominal, 32 levels, 16 MPI ranks, 6 h gate | all known input contracts fixed; dt=60 s numerical blow-up proven; dt=20 s run exited 1 without retained model log | add durable diagnostics, repeat identical dt=20 s gate, then diagnose from evidence |
| Alboran/Gibraltar | planned 1 km tile | profile only; no validated grid/model run | grid preflight, 6 h, then 24 h |
| Gulf of Lion | planned 1 km tile | profile only; no validated grid/model run | grid preflight, 6 h, then 24 h |
| Tyrrhenian | planned 1 km tile | profile only; no validated grid/model run | grid preflight, 6 h, then 24 h |
| Algerian Basin | planned 1 km tile | profile only; no validated grid/model run | grid preflight, 6 h, then 24 h |
| Multi-region staging/API | Western Mediterranean | not assembled | wait for every regional 24 h gate |
| 96/120 h horizons | all tiles | deliberately deferred | geographic coverage has priority |
| Production | existing ETL/API/bucket/pointers | untouched | no promotion authorization yet |

The validated Balearic CROCO grid is stored at:

```text
gs://predsea-daily-outputs-test/static/native-marine/balearic_1km/croco-grid/20260722-v3/croco_grid.nc
```

Do not copy a shortened checksum from chat history. Retrieve and record the
complete checksum/object generation from GCS metadata and the companion
validation report before publication.

The earlier input-contract failure was:

```text
Friendly job: predsea-sim-balearic-1km-croco-1f486f02
Run date:     2026-07-16
Region:       balearic_1km
Model:        CROCO 2.1.3 regional binary
Machine:      c2d-highcpu-16 Standard
Requested:    16 vCPU, 32 GiB, 16 MPI ranks
Result:       FAILED before timestep integration
```

That earlier failure was not VM capacity, preemption, WRF, CMEMS download, grid, or
interpolation. CROCO reported:

```text
GET_TCLIMA - unable to find climatology variable: tclm_time
ERROR: Abnormal termination: netCDF INPUT
```

The generated `croco_clm.nc` used a generic `ocean_time`; the compiled CROCO
readers require `ssh_time`, `uclm_time`, `tclm_time`, and `sclm_time`, expressed
as elapsed model days because this regional binary is compiled without
`USE_CALENDAR`.

The fix is committed, pushed, and tested:

```text
Commit: 03aacfc
Tests: 8 focused CROCO forcing/bulk/namelist tests passed
Image tag: europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch:clmtime-03aacfc
Immutable digest: sha256:ee8244de30d0082f7054d73810321ed113fc339c6f00e1ad688da685882be924
Cloud Build: 32f159a1-05bb-4c29-9be5-f761b3bbd6cb (SUCCESS)
```

Subsequent fixes also added the required SSH and incoming-longwave variables.
CROCO then entered integration and reproduced a STEP2D velocity blow-up with a
60-second baroclinic timestep. Commit `61c8e93` reduced that timestep to 20
seconds while retaining 30 fast barotropic substeps. Image
`sha256:ae0fcf8ccdac53963043a31ffb3af34ada78315b2504caf8ca62a632251e528b`
was tested by Batch job `predsea-sim-balearic-1km-croco-f4323874`, which exited
1 after about 12 minutes. Because that attempt did not preserve application
stdout, its cause remains unknown. The diagnostic rerun described in section 0
is mandatory before changing physics, timestep, forcing or grid again.

The running heartbeat/monitor is named:

```text
continue-predsea-swan-and-croco-staging
```

Keep it until the current bounded staging program reaches a terminal decision.

## 6. Current product configuration

The authority tile is:

```text
simulation/marine/regions/balearic_1km.json
```

Current grid and time configuration:

| Property | Value |
|---|---:|
| Approximate bounds | 0.5°E–5.5°E, 37.5°N–41.5°N |
| Grid | 501 × 401 |
| Nominal resolution | 1 km |
| Grid spacing in SWAN input | approximately 0.01° × 0.01° |
| Forecast window | 2026-07-20 00:00 UTC to 2026-07-21 00:00 UTC |
| Published interval | 1 hour |
| Expected timestamps | 25 |
| Internal SWAN timestep | 5 minutes |
| Wind source | ECMWF Open Data 10u/10v |
| Wind source cadence | available 3-hour steps, 0–24 h |
| SWAN wind cadence | interpolated to exact hourly states |
| Wave boundary source | Copernicus Mediterranean wave parameters |
| Boundary formulation | hourly parametric JONSWAP from VHM0/VTPK/VMDR |
| Native parallel output | structured VTK/PVD |
| Canonical publication output | PredSea NetCDF |

Do not change the internal timestep back to ten minutes: SWAN rejected that
configuration because the geographic propagation CFL exceeded its limit.

## 7. Proven evidence from recent staging attempts

The following are verified facts, not guesses.

### 7.1 ECMWF wind behavior

The ECMWF Open Data source does not provide a separate object for every desired
one-hour step in this workflow. The implemented contract is:

1. download available 3-hour 10u/10v steps 0, 3, 6, ..., 24;
2. validate exactly nine source times and finite 10u/10v values;
3. linearly interpolate them to 25 exact hourly states for SWAN;
4. validate the prepared SWAN wind timeline independently.

Do not assume “hourly product” means ECMWF publishes 25 hourly source objects.
Do not reintroduce SciPy as a hidden runtime dependency; interpolation is
implemented explicitly with NumPy/xarray.

Observed valid wind ranges in the July 20 test were finite and plausible:

```text
10u approximately -32.49 to 27.91 m/s
10v approximately -22.77 to 25.63 m/s
```

### 7.2 Copernicus/CMEMS boundary behavior

The authenticated current boundary product was downloaded and validated. A
validated cache exists at:

```text
gs://predsea-daily-outputs-test/forcing/cmems/2026-07-20/cmems_swan_boundary.nc
```

It contains the required 25-hour boundary timeline for this experiment.
Copernicus credentials must be passed using both supported name families because
client versions differ:

```text
COPERNICUS_USERNAME
COPERNICUS_PASSWORD
COPERNICUSMARINE_SERVICE_USERNAME
COPERNICUSMARINE_SERVICE_PASSWORD
```

Never print passwords in a dry-run manifest. The submission helper redacts both
password fields; preserve that behavior.

### 7.3 Full input preparation

The pipeline has successfully prepared:

- the 501 × 401 bathymetry/grid;
- `bottom.bot`;
- `wind.dat` with 25 hourly states;
- four-boundary TPAR/JONSWAP inputs with 25 timestamps;
- a versioned SWAN command file;
- an input manifest containing hashes and lineage.

Therefore the current unresolved gate is not basic forcing acquisition or SWAN
input creation.

### 7.4 Failures found and fixed

| Attempt | Evidence | Root cause | Fix |
|---|---|---|---|
| Earlier runs | cached ECMWF wind malformed | cache accepted by name, not content | fail-closed payload/time validation and fresh fetch |
| Earlier runs | hourly ECMWF objects absent | wrong source cadence assumption | download 3-hour steps and interpolate hourly |
| Earlier runs | missing SciPy during xarray interpolation | implicit optional dependency | explicit NumPy/xarray interpolation |
| r8 | `swan.exe/swanrun are not installed` | Batch supplied a minimal PATH and `swanrun` executable bit was not guaranteed | prepend `/usr/local/bin`, `chmod 0755`, assert both executables in image build |
| r9 | OpenMPI refused root; no `swan_output.pvd` | Batch container runs as root and OpenMPI requires explicit acknowledgement | set both OpenMPI root acknowledgement variables and fail if PVD is absent |

The required OpenMPI environment variables are:

```text
OMPI_ALLOW_RUN_AS_ROOT=1
OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
```

Do not remove them unless the container is intentionally changed to a non-root
runtime user and that new contract is tested.

The SWAN `swanrun` wrapper returned success even when `mpirun` refused to start.
This is why output existence/content validation is mandatory after execution.

## 8. Exact next actions (updated 2026-07-22)

### Gate A — corrected Balearic CROCO 6-hour run

1. Dry-run `scripts/submit_gcp_batch_simulation.py` with:
   - region `balearic_1km`;
   - model `croco`;
   - forecast hours `6`;
   - run date `2026-07-16` to match retained WRF output;
   - a new immutable run ID;
   - staging bucket `predsea-daily-outputs-test`;
   - location `europe-west1`;
   - `c2d-highcpu-16`, 16000 CPU millicores, 32768 MiB, 16 MPI ranks;
   - provisioning model `STANDARD`;
   - image pinned to `sha256:ee8244de...be924`;
   - the immutable `20260722-v3` grid URI above;
   - the retained July 16 `wrfout_d02_*` staging prefix.
2. Inspect the redacted dry-run manifest. It must contain no credentials and no
   production bucket or pointer.
3. Submit once.
4. Verify, in order:
   - grid/binary dimensions agree (interior LM=499, MM=399; file 501 x 401);
   - exact seven-hour CMEMS coverage and real 3-D depth coverage;
   - exact seven WRF timestamps and required surface variables;
   - `croco_clm.nc` contains all four CROCO time axes with values 0 through
     0.25 elapsed days;
   - CROCO passes initial NetCDF reads and enters integration;
   - no NaN, CFL/blowup, NetCDF, MPI, or domain-decomposition fatal error;
   - history output has seven hourly records and required physical variables;
   - content validation and immutable staging upload pass;
   - success marker is written only after validation.
5. Record elapsed runtime, disk, artifact size, finite fractions and ranges.

### Gate B — Balearic CROCO 24-hour run

Only after Gate A passes, run the same immutable code/grid at 24 hours with 25
hourly CMEMS and WRF timestamps. Do not treat a six-hour pass as permission to
skip full horizon validation.

### Gate C — Western Mediterranean regional expansion

After Balearic CROCO 24-hour validation, prioritize geography over horizon:

1. Alboran/Gibraltar;
2. Gulf of Lion;
3. Tyrrhenian;
4. Algerian Basin.

For each tile: create and validate the exact grid first, compile/pin a matching
CROCO binary, run SWAN and CROCO for six hours, then 24 hours, measure cost and
runtime, and validate overlap continuity. Do not reuse the Balearic binary for
a different grid shape.

### Historical SWAN instructions

The older r10 instructions below remain historical evidence for debugging
SWAN, but r10 is no longer the active gate.

### Historical Gate — monitor r10

1. Describe `predsea-sim-balearic-1km-swan-f8b64f3c`.
2. If scheduled, wait; do not submit duplicates merely because Spot allocation
   is delayed.
3. When running, obtain its UID and inspect Batch logs.
4. Confirm these stages in order:
   - VM allocation and pinned digest pull;
   - cached forcing sync;
   - malformed cache rejection if applicable;
   - ECMWF source validation: nine 3-hour states;
   - SWAN wind preparation validation: 25 hourly states;
   - CMEMS boundary validation: 25 timestamps;
   - native `swanrun` invocation with two MPI ranks;
   - real numerical progress and normal SWAN termination;
   - `swan_output.pvd` and referenced parallel VTK pieces exist;
   - VTK-to-NetCDF canonicalization;
   - canonical NetCDF content validation;
   - upload to the immutable staging run prefix;
   - staging `SUCCESS` marker upload;
   - Batch terminal `SUCCEEDED`.

Expected output prefix:

```text
gs://predsea-daily-outputs-test/predictions/2026-07-20/runs/2026-07-20T0000Z-swan-current-r10/balearic_1km/
```

### Historical Gate — if r10 fails

Do not guess and do not immediately alter physics.

1. Preserve the exact job UID, timestamps, image digest, and final logs.
2. Identify the first failing stage and first causal error, not only the final
   Python exception.
3. Classify it as infrastructure, forcing, preparation, MPI/runtime, numerical,
   canonicalization, validation, or upload.
4. Change one attributable variable whenever practical.
5. Add a regression check at the cheapest boundary that would have caught it.
6. Run focused tests.
7. Commit and push only the intended files.
8. Build a new image with `.gcloudignore.swan`.
9. Require Cloud Build to pass its runtime assertions.
10. pin the new digest;
11. dry-run the next unique run ID;
12. submit once and monitor.

Mechanical staging issues are authorized for autonomous repair. Production is
still out of scope.

### Historical Gate — after r10 succeeds

Success requires all of the following, not merely Batch `SUCCEEDED`:

- exactly 25 timestamps from hour 0 through hour 24;
- full expected geographic coverage;
- mandatory wave variables present;
- at least 90% finite values, with land-mask handling documented;
- physical wave-height, period, and direction ranges;
- no constant or empty fields masquerading as output;
- lineage identifying ECMWF as wind forcing and Copernicus as boundary forcing;
- native provider identified as PredSea SWAN;
- immutable artifact hashes and manifest;
- measured runtime, disk, output size, machine type, and estimated compute cost;
- no writes to production.

Then connect the validated native bundle to the staging publication/API path.
Test route/place JSON and maps using native SWAN values. Keep the existing
Copernicus-backed production response live as fallback.

## 9. Build and submission workflow

Use the reduced build context:

```text
.gcloudignore.swan
```

It exists because the local disk was full and the repository contained many
gigabytes of unrelated outputs, temporary data, environments, and Git objects.
The reduced context is about 30 MiB and intentionally retains:

- `scripts/`;
- `simulation/marine/swan/`;
- `simulation/marine/regions/`;
- `assets/static_grids/balearic_bathymetry_swan.nc`.

Do not solve local disk pressure by deleting user data. Do not silently expand
the build context to include outputs, scratch data, credentials, or virtual
environments.

Representative build shape, after mandatory skill/help validation:

```bash
gcloud builds submit . \
  --config=simulation/marine/swan/cloudbuild.batch.yaml \
  --substitutions=_IMAGE=europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/swan-batch:<unique-tag> \
  --ignore-file=.gcloudignore.swan \
  --project=predsea-api \
  --region=europe-west1 \
  --async \
  '--format=value(id)' \
  --quiet
```

After success, extract `results.images[].digest` and submit using the digest.
Always dry-run `scripts/submit_gcp_batch_simulation.py` first. Use a unique run
ID for each attempt; never reuse an old failed run ID.

## 10. Validation philosophy

Every stage is fail-closed and content-based.

Bad validation patterns to avoid:

- file exists;
- command returned zero;
- logs contain no obvious error;
- object count is nonzero;
- API returned HTTP 200 but values are `None`;
- time coordinate endpoints look right but intermediate times are missing;
- a baseline provider name appears in metadata without real baseline rows;
- a model smoke test is treated as a regional forecast.

Required validation dimensions:

- exact timestamps, cadence, start, and end;
- required variables and dimensions;
- finite fraction and fill values;
- physical value bounds;
- spatial coverage and coordinate orientation;
- ocean/land mask behavior;
- source/model/run/grid lineage;
- hash, size, and immutability;
- observed runtime/disk/cost;
- explicit failure reason.

## 11. Roadmap after the first native SWAN success

Proceed in this order while production remains live:

| Order | Deliverable | Promotion condition |
|---:|---|---|
| 1 | Balearic SWAN 1 km, 24 h | one fully validated staging run |
| 2 | Repeatable unattended SWAN run | at least a second clean cycle; interruption behavior understood |
| 3 | Balearic CROCO 1 km, initially 6 h then 24 h | real 3-D ocean forcing, native output, content validation |
| 4 | Balearic coupled reference bundle | WRF + SWAN + CROCO manifests align in time/space/lineage |
| 5 | Repeatable unattended Balearic native run | at least a second clean cycle; interruption behavior understood |
| 6 | Forecast quality ETL foundation | asynchronous matchups against observations and baselines; never blocks publication |
| 7 | Regional grid and forcing preflight | every planned tile has complete atmospheric/ocean forcing and versioned bathymetry |
| 8 | Additional 1 km regions | Alboran/Gibraltar, Gulf of Lion, Tyrrhenian and Algerian tiles each pass bounded 6 h then 24 h gates |
| 9 | Multi-region staging API | route/place/map tests prove native lineage and non-null data in every supported region and across overlaps |
| 10 | Guarded production promotion | unattended repeatability, rollback, API and customer gates |
| 11 | SWAN/CROCO 96 h benchmark | forcing, stability, disk, runtime and cost margin pass for every promoted tile |
| 12 | SWAN/CROCO 120 h benchmark | only if the operational window retains margin; otherwise retain 96 h |

Geographic coverage has priority over extending the horizon. Do not start the
96/120-hour program until all required Western Mediterranean tiles have passed
their 24-hour gates and the multi-region staging API has been validated. Do not
jump directly to 120 hours before measuring each regional 24-hour run. Project
runtime, disk, and cost from evidence, then test 96 hours if five days lacks
margin. Four days is an acceptable operational product; a late five-day failure
is not.

## 12. CROCO constraints not to forget

The existing surface-current Copernicus file is not sufficient to initialize
CROCO. A valid native ocean run requires at least:

- 3-D temperature;
- 3-D salinity;
- 3-D currents;
- sea-surface height;
- depth/vertical coordinates;
- complete initial conditions;
- complete open-boundary conditions;
- atmospheric surface forcing;
- a versioned regional grid and vertical configuration.

Do not claim a CROCO forecast based on `uo`/`vo` surface fields alone. CROCO
must first pass a bounded six-hour regional benchmark, then 24 hours, before
longer horizons.

## 13. Atmospheric/WRF constraints retained from earlier work

Do not regress these already-discovered invariants:

- derive WRF duration from start/end dates rather than independent hardcoding;
- verify forcing covers the entire requested duration;
- order ECMWF GRIB messages chronologically across pressure and surface data;
- validate WPS timestamps plus mandatory soil/snow field inventory;
- reject `parent_grid_ratio=1` for active child domains;
- reject MPI decompositions that create undersized patches;
- distinguish `met_em` inputs from `wrfout` outputs using names and content;
- size disk from measured output volume with margin;
- set runtime timeout from measured throughput with margin;
- use bounded early stability/throughput gates;
- preserve checkpoints and reuse downloaded forcing after infrastructure failure;
- use Spot only for retryable stages and retain a Standard fallback strategy.

The stable emergency atmosphere topology was two domains at 3 km, not seven
same-resolution nested domains. A 3 km/24 h success does not prove a 1 km/5-day
forecast.

## 14. Forecast quality and observations

Quality evaluation is a separate asynchronous ETL and must never block daily
forecast publication.

Required comparison structure:

```text
PredSea raw forecast
Copernicus/ECMWF baseline sampled at identical point/time
quality-controlled observation sampled at identical point/time
        --> matchup with spatial/time offsets and rejection reason
        --> metrics by model, variable, region, station, lead band, and regime
```

Observations, not Copernicus, are ground truth. Compare all models on identical
matched samples. Never silently drop a missing sample for only one model.

Minimum metrics:

- bias, MAE, RMSE, correlation, centered RMSE, sample count;
- circular direction bias/MAE;
- detection, false-alarm ratio, critical success index, Brier score where valid;
- peak-condition error, threshold-crossing timing, best-window agreement, and
  unsafe false negatives for route products;
- availability, latency, coverage, and rejection counts.

Stratify at least by lead bands 0–24, 25–48, 49–72, 73–96, and 97–120 hours.
Preserve raw output. Compute verification before bias correction. Train any
correction only on earlier cycles and evaluate on later untouched cycles.

New observation locations must be registry/config driven where possible. A new
provider needs a connector, normalization/QC tests, and a registry entry; it
must not require changes to WRF/SWAN/CROCO physics.

## 15. Multi-region expansion

After Balearic success and repeatability, add one independent tile at a time:

1. `balearic_1km` — eastern Spain and Balearics;
2. `alboran_1km` — southern Spain and Gibraltar;
3. `gulf_of_lion_1km` — southern France;
4. `tyrrhenian_1km` — western Italy, Corsica, Sardinia;
5. `algerian_1km` — southern western Mediterranean.

Each region needs versioned bounds, grid, bathymetry, timestep, forcing
coverage, observation registry, runtime/disk/cost measurements, and an
independent promotion decision. Inland destinations must not enlarge marine
compute domains.

Current profiles imply the following planning geometry. The point counts below
are profile-derived estimates using the present 0.01-degree spacing convention;
they are **not validated CROCO file dimensions** until each grid job emits and
checks the actual NetCDF. Because longitude distance changes with latitude,
0.01 degree is only nominally 1 km.

| Tile | Bounds (lon, lat) | Planned points (x by y) | Nominal points | Status |
|---|---|---:|---:|---|
| Balearic | 0.5..5.5, 37.5..41.5 | 501 x 401 | 200,901 | validated grid |
| Alboran/Gibraltar | -6.0..-1.0, 35.0..37.5 | about 501 x 251 | 125,751 | estimate only |
| Gulf of Lion | 2.0..6.5, 41.5..44.5 | about 451 x 301 | 135,751 | estimate only |
| Tyrrhenian | 7.5..14.0, 38.0..44.5 | about 651 x 651 | 423,801 | estimate only |
| Algerian Basin | -1.0..8.5, 35.0..38.0 | about 951 x 301 | 286,251 | estimate only |

The current model/resource planning contract is:

| Model/stage | Spatial/vertical configuration | Time configuration | Initial VM plan |
|---|---|---|---|
| WRF atmospheric source | Western Mediterranean 3 km, stable two-domain topology | hourly publication; retain the exact proven namelist timestep rather than guessing it from documentation | historical large Standard VM; re-measure before production sizing |
| SWAN per tile | nominal 1 km, 36 directions, 32 frequencies | 5-minute internal step, hourly output, 6 h then 24 h | 16 vCPU Standard benchmark; tune only from measured scaling |
| CROCO per tile | nominal 1 km, 32 sigma levels; binary compiled to exact grid interior | current Balearic gate uses 60-second 3-D step and 30 fast 2-D substeps; hourly output | `c2d-highcpu-16` Standard, 16 MPI ranks, 32 GiB for gates |
| Canonicalization/validation | native model grid | exact hour 0 through requested horizon | Batch task/container; must fit measured disk and memory |

Vertical-level rationale: the choice of 32 sigma levels is informed by Juza et
al. (2016), “SOCIB operational ocean forecasting system and multi-platform
validation in the Western Mediterranean Sea,” *Journal of Operational
Oceanography*, 9:sup1, s155–s166,
https://doi.org/10.1080/1755876X.2015.1117764. This citation applies only to
the vertical discretization count. WMOP is a ROMS configuration at
approximately 2 km horizontal resolution over a different domain; it is not a
one-to-one validation of PredSea's CROCO implementation or nominal 1 km
regional setup.

Never copy those resource/timestep values blindly to a new coast. Tyrrhenian
and Algerian are substantially larger than Balearic, while Gibraltar has a
narrow, dynamically sensitive exchange. Each tile must pass its own CFL,
decomposition, disk, runtime, open-boundary, and physical-value gates.

Gibraltar is included by the Alboran bbox, but geographic inclusion alone is
not acceptance. Its dedicated gate must verify:

- the Strait is wet and resolved in the versioned bathymetry/mask;
- east and west open-boundary data cover the complete water column and time;
- tidal constituents are explicitly sourced and enabled if required;
- two-layer Atlantic/Mediterranean exchange direction and transport are
  physically plausible;
- no artificial wall, land bridge, smoothing closure, or edge extrapolation
  blocks the Strait;
- overlap fields agree with adjacent tiles within documented tolerances.

Do not assume a configuration stable for one coastline is stable for another.
Bathymetry, open boundaries, winds, numerical timestep, observations, and cost
must be validated per region.

## 16. Definition of done

The overall project is not done until:

1. native SWAN waves run unattended and repeatably;
2. native CROCO ocean runs unattended and repeatably;
3. WRF/SWAN/CROCO produce aligned, validated, immutable PredSea bundles;
4. staging API and Relay outputs use real non-null native values with lineage;
5. quality ETL compares PredSea, external baselines, and observations fairly;
6. runtime, disk, cost, quota, retry, and rollback behavior are measured;
7. production promotion is atomic, reversible, and does not remove fallback;
8. additional regions can be added through versioned profiles and bounded
   validation rather than bespoke production edits.

Until then, label all native marine output as staging/experimental and preserve
the current production fallback.

## 17. Related documents

Read these for deeper history and design context:

- `docs/native-marine-forecast-plan.md`
- `docs/etl-definitive-solution-plan.md`
- `docs/ai-agent-master-handoff-2026-07-16.md`
- `docs/etl-agent-handoff-2026-07-16.md`
- `docs/real-validation-runbook.md`

When facts conflict, prefer current GCP evidence, current code/tests, and this
dated handoff. Update this document after every terminal run or material design
decision so the next agent does not inherit stale assumptions.
