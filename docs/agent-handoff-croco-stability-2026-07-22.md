# PredSea Native Marine Forecast — CROCO Stability Handoff

Last updated: **2026-07-22 22:45 Europe/Madrid**  
Repository: `/Users/charles.santana/PredSea/predsea-system`  
Google Cloud project: `predsea-api`  
Primary GCP location: `europe-west1`  
Development branch on origin: `codex/wrf-curvilinear-publication`

This document is a continuation contract for another AI agent. It describes
the exact objective, scope, evidence, current blocker, permissions, prohibited
actions, and next validation sequence. Read it before changing code or cloud
resources. When this document conflicts with older status text, prefer current
GCP evidence, current code/tests, and this dated document.

## 1. Final goal

Build an unattended PredSea-owned Western Mediterranean forecasting system in
GCP that produces aligned, hourly atmospheric, wave, and ocean products:

```text
ECMWF forcing -> WPS/WRF -> PredSea atmosphere
                              |          |
                              v          v
                         SWAN waves   CROCO ocean
                              \          /
                        validated regional bundles
                                   |
                            staging API -> Relay
                                   |
                        guarded production promotion
```

The target spatial product is a collection of independently validated nominal
1 km marine tiles. Geographic coverage has priority over extending forecast
horizon from 24 hours to 96/120 hours.

Copernicus Marine/CMEMS is an upstream initial/open-boundary source, independent
comparison baseline, and fallback. It is not native PredSea forecast output.
ECMWF supplies atmospheric forcing; PredSea WRF produces the atmospheric model
forecast used by the native marine models.

## 2. Hard authorization boundary

### Authorized without asking again

- Read repository files and staging artifacts.
- Run local tests and offline diagnostics.
- Make scoped mechanical and numerical-preparation fixes supported by evidence.
- Commit and push scoped changes to `codex/wrf-curvilinear-publication`.
- Build immutable staging images in `predsea-api`.
- Dry-run and submit bounded GCP Batch experiments writing only to the staging
  bucket.
- Stop wasting compute after a failed or unsuitable bounded gate.
- Preserve run-scoped failure diagnostics.

### Strictly out of scope unless the user explicitly authorizes it later

- Do not change any production Cloud Run service or job.
- Do not change production scheduler configuration.
- Do not change IAM, service accounts, roles, or API enablement.
- Do not write or advance any production `latest` pointer.
- Do not write model artifacts to production buckets.
- Do not delete cloud resources or staging evidence.
- Do not promote native output to customers.
- Do not replace the current Copernicus-backed production fallback.

All current native work must remain under:

```text
gs://predsea-daily-outputs-test/
```

Use unique run IDs and immutable, run-scoped object prefixes. Never reuse a
failed run ID.

## 3. Geographic boundary and order

The required regional sequence is:

| Order | Region | Bounds (longitude, latitude) | Planning grid | Acceptance note |
|---:|---|---|---:|---|
| 1 | `balearic_1km` | 0.5..5.5 E, 37.5..41.5 N | 501 x 401 validated | Reference implementation |
| 2 | `alboran_1km` | -6.0..-1.0 E, 35.0..37.5 N | 501 x 251 | Must explicitly validate Gibraltar |
| 3 | `gulf_of_lion_1km` | 2.0..6.5 E, 41.5..44.5 N | 451 x 301 | Southern France/Gulf of Lion |
| 4 | `tyrrhenian_1km` | 7.5..14.0 E, 38.0..44.5 N | 650 x 651 | Western Italy/Corsica/Sardinia |
| 5 | `algerian_1km` | -1.0..8.5 E, 35.0..38.0 N | 951 x 301 | Southern Western Mediterranean |

These bounds and dimensions match the current region profiles under
`simulation/marine/regions/`, which are the source of truth. Nominal 0.01
degree is not exactly 1 km and changes physical distance with latitude.

Gibraltar is not accepted merely because it lies inside the Alboran bounding
box. Its dedicated gates must show:

- a wet, open Strait without an artificial land bridge;
- bathymetry that resolves the gateway without excessive pressure-gradient
  error;
- complete east/west water-column boundary forcing;
- tides if the selected operational configuration requires them;
- physically plausible Atlantic inflow and Mediterranean outflow direction and
  transport;
- overlap continuity with adjacent tiles;
- no extrapolated edge values masquerading as real forcing.

Inland destinations must not enlarge marine compute domains.

## 4. Current component status

| Component/gate | Status | Evidence or next action |
|---|:---:|---|
| Staging isolation and immutable runs | ✅ | GCP Batch plus `predsea-daily-outputs-test`; production untouched |
| PredSea WRF 3 km / 24 h source | ✅ retained | Stable two-domain atmospheric output used for marine forcing |
| Balearic SWAN 1 km / 24 h | ✅ | 25 hourly native-wave timestamps validated in staging |
| Balearic CROCO grid | ✅ structural | 501 x 401 rho points, 32 levels, wet fraction about 0.929, max rx0 0.20 |
| CMEMS 3-D forcing acquisition | ✅ | u/v, temperature, salinity, SSH with hourly coverage |
| WRF bulk atmospheric forcing | ✅ | Exact retained hourly source coverage for bounded gate |
| CROCO binary/grid dimension agreement | ✅ | LM=499, MM=399, N=32 matches file grid |
| Dedicated `croco_bry.nc` generation | ✅ mechanical | CROCO logs prove `GET_BRY` reads hours 0, 1, and 2 |
| Balearic CROCO 6 h stability | ❌ blocker | Repeatable `STEP2D BLOW UP` near simulated 1 h 24 min |
| Balearic CROCO 24 h | ⬜ | Only after a fully validated 6 h pass |
| Other four regions | ⬜ | Profiles only; each needs independent grid and 6 h/24 h gates |
| Multi-region staging API | ⬜ | Intentionally after geographic model gates |
| 96/120 h horizons | ⬜ | Intentionally after all-region 24 h coverage |
| Production promotion | ⬜ | Explicit later decision only |

## 5. Exact latest run and immutable evidence

Latest attempt:

```text
Batch job: predsea-sim-balearic-1km-croco-a67900b2
Run ID: 2026-07-16T0000Z-croco-balearic-6h-v11-boundary
State: FAILED
Created: 2026-07-22T20:08:41Z
Running: 2026-07-22T20:09:42Z
Failed: 2026-07-22T20:21:31Z
Machine: c2d-highcpu-16 STANDARD
Resources: 16 vCPU, 32 GiB, 16 MPI ranks
CROCO 3-D timestep: 20 seconds
Fast 2-D substeps: 30
Requested model horizon: 6 hours
Expected published records: 7 (hour 0 through hour 6)
Image digest: sha256:538592720b36832a08d5a22333880f6f55a941d469dc36398e49055071dbf92c
```

Failure diagnostics:

```text
gs://predsea-daily-outputs-test/predictions/2026-07-16/runs/
  2026-07-16T0000Z-croco-balearic-6h-v11-boundary/
  balearic_1km/failure-diagnostics/croco_balearic_1km/
```

Local diagnostic copy created during investigation:

```text
/private/tmp/predsea-croco-v11/
```

Important commits already pushed:

```text
c3d5f26 fix: constrain CROCO open boundaries
829d612 fix: wire CROCO boundary file into runtime
```

Do not assume `/private/tmp` survives a machine restart. GCS is the durable
source of evidence.

## 6. What v11 proved

The run successfully:

1. acquired and prepared the exact retained WRF/CMEMS inputs;
2. loaded a grid matching the compiled binary;
3. loaded initial and climatology files;
4. loaded dedicated boundary values through `GET_BRY`;
5. started MPI integration;
6. wrote the initial and first-hour history records;
7. preserved logs, input files, forcing files, partial output, and a structured
   failure marker after the model aborted.

The model then failed reproducibly at approximately 0.058 days, around 1 hour
24 minutes:

```text
STEP2D: ABNORMAL JOB END — BLOW UP
VMAX overflow / about 971245 m/s
reported locations include (i,j) approximately (487,56) and (286,18)
```

The first location is near the eastern edge and the second is near the southern
edge. The same timing/location class appeared before dedicated boundary forcing
was enabled. Therefore:

- malformed or unread boundary files are not the primary explanation;
- reducing the timestep from 60 seconds to 20 seconds did not remove the
  failure;
- a Batch exit code alone is not the diagnosis; the application log is;
- the model is not eligible for 24-hour execution.

## 7. Leading root-cause hypothesis: vertical-coordinate inconsistency

This is the strongest new finding, but it remains a hypothesis until a
controlled corrected run passes.

The runtime CROCO configuration uses:

```text
NEW_S_COORD
N = 32
THETA_S = 6.0
THETA_B = 0.0
Hc = 10 m
```

CROCO reports a nonlinear stretched `Cs_r/Cs_w` vertical grid. However,
`scripts/prepare_croco_forcing.py` currently prepares fields using:

```python
s_rho = np.linspace(-1 + 1/(2*N), -1/(2*N), N)
target_z = s_rho * h
```

That is a linear sigma depth and does not reproduce CROCO's configured
`NEW_S_COORD` stretching. The same script computes depth-averaged currents as:

```python
ubar_clm = u_clm.mean(axis=1)
vbar_clm = v_clm.mean(axis=1)
```

An arithmetic level mean is not guaranteed to equal the thickness-weighted
barotropic transport on CROCO's stretched vertical layers. Consequently, the
3-D velocity/density fields and their 2-D barotropic counterparts may describe
different physical water columns. That can excite the split-explicit 2-D mode
and is consistent with a repeatable `STEP2D` blow-up that does not respond to a
smaller 3-D timestep.

Other relevant evidence:

- initial CMEMS values are finite and physically plausible;
- dedicated boundary values are finite and plausible;
- by hour 1 the history output contains 3-D speeds near 4.7 m/s and barotropic
  speeds around 1.1 m/s, much larger than the initial CMEMS currents;
- max bathymetric rx0 is exactly 0.20, the configured ceiling;
- CROCO reports zero base `visc2`, tracer diffusion, and explicit linear and
  quadratic drag values in the parsed namelist, although compiled mixing,
  sponge, and minimum drag options remain active;
- forcing all four open boundaries did not change the failure time materially.

Do not call bathymetry or viscosity the proven cause yet. Do not change several
physics knobs at once and then claim attribution.

## 8. Immediate continuation plan

### Gate 8A — offline vertical-coordinate and transport correction

Do this before another GCP model run.

1. Read the pinned CROCO 2.1.3 `NEW_S_COORD` source routines used by the built
   binary. Do not copy a formula from memory or another ROMS/CROCO version.
2. Implement one shared vertical-coordinate function that derives the exact
   `s_rho`, `s_w`, `Cs_r`, `Cs_w`, and physical rho/w depths from:
   - `N`;
   - `THETA_S`;
   - `THETA_B`;
   - `Hc`;
   - local bathymetry;
   - sea level where required by the selected transform.
3. Use the same vertical configuration source of truth in:
   - grid metadata;
   - initial-condition interpolation;
   - climatology interpolation;
   - boundary interpolation;
   - validation.
4. Interpolate CMEMS temperature, salinity, u, and v onto the actual CROCO
   physical depths, including correct staggered u/v bathymetry.
5. Compute `ubar` and `vbar` from thickness-weighted vertical transport on the
   matching staggered grid. Do not use an unweighted `mean(axis=1)`.
6. Add fail-closed checks comparing supplied `ubar/vbar` with the vertical
   integral reconstructed from supplied `u/v`. Define and document an explicit
   numerical tolerance.
7. Validate rho/u/v staggering, dimension names, vertical ordering, time axes,
   masks, finite fractions, and physical ranges.
8. Add focused regression tests that fail under the current linear-sigma and
   unweighted-mean implementation.

### Gate 8B — corrected bounded CROCO A/B test

After Gate 8A tests pass:

1. Commit only the vertical-coordinate/transport fix and its tests.
2. Push the scoped commit to `codex/wrf-curvilinear-publication`.
3. Build a new immutable CROCO Batch image.
4. Record the Cloud Build ID and immutable digest.
5. Dry-run the submission helper and inspect the redacted manifest.
6. Reuse the same date, region, WRF source, CMEMS source, grid, machine, MPI
   layout, boundary formulation, timestep, and six-hour horizon as v11.
7. Change only the forcing vertical-coordinate/transport preparation.
8. Submit once with a new unique run ID.
9. Require durable diagnostics on either success or failure.

Success is not merely passing the previous 1 h 24 min point. It requires:

- normal completion of all six simulated hours;
- exactly seven hourly history records;
- no `BLOW UP`, NaN, Inf, MPI, NetCDF, or validation errors;
- mandatory zeta/u/v/ubar/vbar/temp/salt fields;
- documented finite fractions and physical ranges;
- full configured coverage and correct masks;
- immutable output, manifest, hashes, runtime, disk, and cost evidence;
- a `SUCCESS` marker written only after content validation.

### Gate 8C — if the corrected A/B still fails

Do not immediately combine arbitrary fixes. Preserve diagnostics and classify
the first causal signal. Then run controlled experiments in this order:

1. quantify pressure-gradient error and locate max rx0/rx1 relative to the
   failing wet cells;
2. verify net volume transport and corner consistency across all open
   boundaries;
3. inspect mask topology and shallow/deep transitions near failing cells;
4. compare no-atmospheric-forcing or rest-state spin-up only if it isolates the
   pressure/boundary mechanism;
5. evaluate a stricter bathymetry gate such as rx0 <= 0.10 as its own grid A/B;
6. evaluate explicit viscosity/drag/sponge settings as a separate A/B using
   values justified from the pinned CROCO source/examples and grid scale;
7. only then reconsider timestep or fast-mode substeps.

Never change grid smoothing, viscosity, boundary formulation, and timestep in
one experiment. That would make a pass scientifically unattributable.

## 9. After the Balearic reference passes

Proceed in this exact order:

1. Balearic CROCO 6 h content gate.
2. Balearic CROCO 24 h content/stability/runtime/disk/cost gate.
3. Build and validate Alboran/Gibraltar SWAN and CROCO grids and forcing.
4. Run Alboran/Gibraltar 6 h, then 24 h.
5. Repeat independently for Gulf of Lion.
6. Repeat independently for Tyrrhenian.
7. Repeat independently for Algerian Basin.
8. Validate overlaps, time alignment, authority, and continuity across tiles.
9. Assemble an immutable multi-region staging bundle.
10. Test the staging API and Relay-facing route/place/map data across all
    supported regions, including cross-tile routes.
11. Establish unattended repeatability and rollback.
12. Only then evaluate 96 hours and 120 hours. A stable 96-hour product is
    acceptable if 120 hours does not retain operational margin.
13. Production promotion remains a separate explicit user decision.

Do not reuse the Balearic CROCO binary for a different grid shape. CROCO is
compiled for exact interior dimensions and region-specific physics.

## 10. Model and compute contract

Current measured/planned configurations:

| Model/stage | Configuration | Time/output | Initial GCP plan |
|---|---|---|---|
| WRF source | Stable Western Mediterranean 3 km, two-domain topology | hourly | Existing retained staging output |
| SWAN per tile | nominal 1 km, 36 directions, 32 frequencies | 5-minute internal step, hourly output | 16-vCPU Standard benchmark |
| CROCO Balearic gate | nominal 1 km, 501 x 401 rho, 32 stretched levels | 20-second 3-D step, 30 fast substeps, hourly output | `c2d-highcpu-16` Standard, 16 MPI, 32 GiB |
| Canonicalization/validation | native grid | exact hour 0..horizon | run-scoped Batch task |

Do not copy these values blindly to Gibraltar or another coastline. Each region
must independently pass CFL, decomposition, bathymetry, forcing, boundary,
runtime, disk, and physical-value gates.

## 11. Data contracts that must remain fail-closed

### CROCO minimum forcing

- three-dimensional temperature;
- three-dimensional salinity;
- three-dimensional u/v currents;
- sea-surface height;
- explicit vertical coordinates and their configuration;
- initial conditions;
- complete open-boundary conditions;
- WRF atmospheric bulk forcing;
- versioned regional grid, mask, and bathymetry.

Surface `uo/vo` alone is not a CROCO forecast input.

### Required validation

- exact timestamps, cadence, start, end, and count;
- complete variables and dimensions;
- vertical coordinates and positive layer thickness;
- 3-D/2-D transport consistency;
- finite fractions and fill values;
- physical value limits;
- spatial bounds and coordinate orientation;
- wet/land mask behavior;
- open-boundary and corner consistency;
- run/source/model/grid/image lineage;
- object hash, size, and immutability;
- measured runtime, disk, and compute cost;
- explicit failure reason.

File existence, exit code zero, HTTP 200, or a nonempty object list are not
sufficient validation.

## 12. Repository and Git safety

The worktree contains unrelated user changes and intentional removals of large
local shapefiles and NetCDF files. These belong to the user.

- Never restore, delete, stage, or commit unrelated files.
- Never use `git reset --hard` or destructive checkout commands.
- Inspect scoped diffs.
- Stage explicit paths only.
- Run focused tests and `git diff --check` before commit.
- Push explicit commits to `origin/codex/wrf-curvilinear-publication` even if
  the local checkout is detached.
- Use `.gcloudignore.swan` or the appropriate reduced build context; do not
  upload large outputs, environments, `.git`, or credentials to Cloud Build.

## 13. GCP operating procedure

Before every `gcloud` command, read completely:

```text
.agents/skills/gcloud/SKILL.md
```

Then validate the exact leaf syntax using `gcloud help <leaf command>`. Follow
all skill constraints, including:

- one gcloud command at a time;
- no pipes, shell chaining, substitutions, or redirection in gcloud commands;
- explicit `--project=predsea-api`;
- explicit location/region/zone;
- `--quiet`;
- reduced/filter/projected output;
- dry-run where supported;
- immutable digest pinning;
- no IAM, deletion, billing, API-enablement, or production mutations.

Batch `SUCCEEDED` is not model success until artifact contents pass validation.
Batch `FAILED` is not a diagnosis until application diagnostics are read.

## 14. Forecast-quality infrastructure

Quality evaluation is asynchronous and must not block daily publication.
Compare PredSea raw forecasts, Copernicus/ECMWF baselines, and quality-controlled
observations on identical point/time samples. Observations are ground truth;
Copernicus is a baseline.

Preserve model cycle, valid time, lead hour, coordinates, region/grid version,
forcing lineage, spatial/time offsets, values, QC flags, and rejection reasons.
Report at least bias, MAE, RMSE, correlation, circular directional errors,
sample count, availability, latency, peak timing, threshold crossings, and
unsafe false negatives by lead band and region.

New observation locations should be registry/config driven. A new provider
requires a connector, normalization/QC tests, and registry entry; it must not
require changes to WRF/SWAN/CROCO physics.

## 15. Definition of done

The project is complete only when:

1. SWAN and CROCO run unattended and repeatably in every required tile;
2. WRF/SWAN/CROCO outputs align in time, space, variables, and lineage;
3. every run is content-validated and immutable;
4. all Western Mediterranean overlaps and Gibraltar-specific gates pass;
5. staging API and Relay return real, non-null native values and maps;
6. quality ETL compares native forecasts fairly with baselines/observations;
7. runtime, disk, cost, quota, retry, checkpoint, and rollback are measured;
8. an unattended repeat cycle succeeds;
9. production promotion is atomic, reversible, explicitly authorized, and
   retains fallback coverage.

Until then, label native marine output as staging/experimental.

### Vertical discretization reference

PredSea uses 32 sigma levels as its vertical discretization choice, informed by
the 32 stretched sigma levels documented for SOCIB's Western Mediterranean
Operational Forecasting System (WMOP): Juza et al. (2016), “SOCIB operational
ocean forecasting system and multi-platform validation in the Western
Mediterranean Sea,” *Journal of Operational Oceanography*, 9:sup1, s155–s166,
https://doi.org/10.1080/1755876X.2015.1117764.

This citation supports only the choice of 32 vertical levels. WMOP is a ROMS
configuration with approximately 2 km horizontal resolution over a different
domain; it does not validate PredSea's CROCO implementation, nominal 1 km
regional grids, or complete physical configuration.

## 16. Required reading

Read these after this handoff for broader context:

- `docs/native-marine-forecast-plan.md`
- `docs/agent-handoff-native-marine-2026-07-21.md`
- `docs/etl-definitive-solution-plan.md`
- `docs/ai-agent-master-handoff-2026-07-16.md`
- `docs/etl-agent-handoff-2026-07-16.md`
- `docs/real-validation-runbook.md`

Update this document after every terminal experiment or material design change.
Record evidence, not guesses, and clearly distinguish proven facts from working
hypotheses.
