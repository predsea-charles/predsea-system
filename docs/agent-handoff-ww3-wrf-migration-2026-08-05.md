# PredSea — SWAN→WW3 Migration & WRF Domain Fix — Handoff

Last updated: **2026-08-05 (Europe/Madrid)**
Repository: `/Users/charles.santana/PredSea/predsea-system`
Google Cloud project: `predsea-api`
Primary GCP location: `europe-west1`
Bucket in use for all work described here: `gs://predsea-daily-outputs-test/` (production untouched)

This document is a continuation contract for another AI agent. It describes
the exact objective, scope, evidence, current blocker, permissions, and next
steps for the wave-engine migration and the WRF domain fix it now depends on.
Read it before changing code or cloud resources. When this document conflicts
with older status text (including `docs/ww3-migration-plan-2026-08-04.md`),
prefer this document and current GCP evidence.

## 1. Final goal

Replace SWAN with WaveWatch III (WW3) as PredSea's wave-spectral engine,
project-wide across all 5 regions, then validate a 24-hour forecast using
WRF's own atmospheric output as WW3's wind forcing (not the ECMWF Open Data
shortcut used for earlier smoke tests):

```text
ECMWF forcing --------------------------------\
                                                v
                                    WPS/WRF (24h, 2-domain)
                                       |                 \
                                       v                  v
                              wrfout_d01/d02        (future: CROCO bulk forcing,
                                       |              unchanged from today)
                                       v
                        WW3 wind adapter (ww3_prnc input) -- NOT YET BUILT
                                       |
                                       v
                     WW3, 5 regions, proportional-core Batch jobs
                                       |
                                       v
                        validated regional wave bundles
```

This is a **full replacement** of SWAN, not a hybrid, per the 2026-08-04
decision recorded in `docs/ww3-migration-plan-2026-08-04.md` §"decisions
locked in." Do not re-litigate that decision without new evidence.

## 2. Hard authorization boundary

### Authorized without asking again

- Read repository files and GCS staging artifacts.
- Run local tests, `ww3_grid`/`ww3_prnc` offline diagnostics.
- Make scoped mechanical fixes to WW3/WRF preprocessing scripts.
- Build immutable staging images in `predsea-api` **via Cloud Build only**
  (see Section 2a — no local `docker build`).
- Submit bounded GCP Batch/GCE experiments writing only to
  `gs://predsea-daily-outputs-test/`.
- Stop wasting compute after a failed or unsuitable bounded gate.
- Preserve run-scoped failure diagnostics (including the periodic
  background-log-upload pattern in Section 6).

### Strictly out of scope unless the user explicitly authorizes it later

- Do not change any production Cloud Run service or job.
- Do not touch `med_basin_1km.json` or the basin-wide SWAN VM step.
- Do not write model artifacts to production buckets.
- Do not delete cloud resources or staging evidence.
- Do not promote WW3 output to customers or flip the API's provider-priority
  logic away from `predsea_swan`.
- Do not run two concurrent WRF-class VMs (64 vCPU each) or otherwise exceed
  the project's single global `CPUS_ALL_REGIONS` 64-vCPU quota — WRF,
  basin-wide SWAN/WW3, and CROCO Batch jobs all draw from this same pool and
  must run sequentially, never concurrently (see `cloudbuild.6h-gate.yaml`'s
  own comments).

### 2a. Standing constraint: everything runs on Google Cloud, never local Docker

This was reaffirmed explicitly this cycle: all image builds go through Cloud
Build (`gcloud builds submit --config=cloudbuild.<name>.yaml --async .`), all
model execution runs on GCP Batch or GCE, never a local `docker build`/`docker
run`, even though `README.md`'s documented dev workflow shows a local build
command. If a new image needs building, author a `cloudbuild.<name>.yaml`
(see the three existing examples: `cloudbuild.wrf.yaml`,
`cloudbuild.ww3-batch.yaml`, `cloudbuild.croco-batch.yaml`) rather than
falling back to the README's local instructions.

## 3. Region bounds (unchanged by this migration)

| Region | Longitude range | Latitude range | Grid (approx.) |
| :--- | :---: | :---: | :---: |
| Alboran | −6.0° to −1.0° | 35.0° to 37.5° | 501×251 |
| Algerian | −1.0° to 8.5° | 35.0° to 38.0° | 951×301 |
| Balearic | 0.5° to 5.5° | 37.5° to 41.5° | 501×401 |
| Gulf of Lion | 2.0° to 6.5° | 41.5° to 43.3° | 500×200 |
| Tyrrhenian | 7.5° to 14.0° | 38.0° to 44.5° | 650×651 |

Source of truth: `simulation/marine/regions/*.json`. See
`docs/whitepaper/02_modeling_suite.md` §4.4 for why Gulf of Lion's northern
edge was resized from 44.5° to 43.3° (land-adjacent boundary bug, unrelated
to this migration but relevant if you touch that region's grid again).

## 4. Current component status

| Component/gate | Status | Evidence or next action |
| :--- | :---: | :--- |
| WW3 image build (`ww3-batch`, ST4 physics) | ✅ | Pushed to `europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/ww3-batch:latest` |
| WW3 single-region 6h smoke test (alboran) | ✅ | 64 vCPU, completed successfully — first proof WW3 runs on the region that motivated the migration |
| WW3 5-region 6h breadth test, uniform 16 vCPU | ❌ | All 5 failed on Batch timeout (exit 50005) at `maxRunDuration=1800s` — insufficient cores for the budget, not a solver crash |
| WW3 5-region 6h breadth test, proportional cores | ✅ | All 5 regions succeeded — see Section 6 for exact job names/timings |
| WRF 24h run (ECMWF-forced smoke test) | ✅ | Completed, but superseded — user decided to use WRF's own output as WW3 wind forcing instead of the ECMWF shortcut |
| WRF domain coverage vs. alboran_1km bbox | ❌ blocker | d01 only reaches lon −3.96°, missing alboran's western ~40% including its whole boundary-point edge (lon −6.0°) |
| WRF domain fix (`setup_domain.py`) | ✅ code fix, ⬜ unverified | `BalearicDomain` dataclass edited (Section 7); image rebuild in progress, not yet re-run |
| WRF→WW3 wind adapter (`ww3_prnc` input) | ⬜ not started | No code written yet — see Section 8 |
| WW3 24h, 5-region test (WRF-forced) | ⬜ blocked | Blocked on the two items above |

## 5. Why WW3 at all (one-paragraph summary; full detail in `docs/ww3-migration-plan-2026-08-04.md`)

Basin-wide and per-region SWAN both hit an identical, repeatable
non-convergence ("stuck at output request 1") in `alboran_1km`,
`gulf_of_lion_1km`, and `algerian_1km`. Five independent variables were
tried and ruled out: bathymetry quality, resolution/timestep, physics scheme,
MPI rank count, and domain size (a standalone small `alboran_1km` job hit the
same wall). The conclusion was something structural to SWAN's implicit
solver on this coastline geometry, motivating a full swap to WW3's explicit,
basin-scale-oriented propagation scheme — a different algorithmic path
through the same wave-action-balance physics, not a parameter change.

## 6. Exact latest run and immutable evidence

### 6.1 5-region 6h WW3 breadth test — SUCCESS (proportional core split)

```text
Script: ww3_submit_5_region_proportional.sh
maxRunDuration: 10800s (3h)
Cores/machine per region (workload-proportional, from ww3_grid sea-point counts):
  tyrrhenian_1km:   24 vCPU, n2-custom-24-24576
  balearic_1km:     16 vCPU, n2-highcpu-16
  algerian_1km:     12 vCPU, n2-custom-12-12288
  alboran_1km:       8 vCPU, n2-highcpu-8
  gulf_of_lion_1km:  4 vCPU, n2-highcpu-4

Batch job names:
  ww3-smoke-tyrrhenian-1km-1785883129
  ww3-smoke-balearic-1km-1785883130
  ww3-smoke-algerian-1km-1785883131
  ww3-smoke-alboran-1km-1785883132
  ww3-smoke-gulf-of-lion-1km-1785883133

Result: all 5 SUCCEEDED. Completion times ranged 1.39h-2.03h (exact
per-region wall-clock times were read from each region's run_trace.log at
the time but are not repeated here verbatim -- re-derive from
gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/<region>-output/run_trace.log
if exact figures are needed for a report).

Output paths:
  gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/<region>-output/
```

### 6.2 5-region 6h WW3 breadth test — FAILED (uniform 16 vCPU, first attempt)

All 5 regions failed at `maxRunDuration=1800s` with Batch exit code 50005
("task runs over the maximum runtime"), within 0.15s of each other,
confirming a pure timeout rather than a repeat of SWAN's non-convergence or
the earlier SIGBUS crash. **No diagnostic data was uploaded for any region**
in this attempt — Batch hard-kills the container tree before any trailing
`gsutil cp` can run, which is why the proportional-split rerun (6.1) added a
background periodic log-uploader (30s interval, PID captured and killed
after the main computation, so a recent `run_trace.log` snapshot survives
even a future timeout-kill).

### 6.3 WRF 24h runs (ECMWF-forced; superseded by the WRF-as-forcing decision)

```text
Run 1 (pre-domain-fix): instance predsea-sim-2026-08-05-053932
  d01: lat [34.94, 44.78] lon [-3.96, 13.96], U10/V10 present
  d02: lat [36.61, 44.00] lon [0.47, 10.76], U10/V10 present

Run 2 (after first, INEFFECTIVE domain edit -- see Section 7): instance
  predsea-sim-2026-08-05-101201
  d01: lat [34.94, 44.78] lon [-3.96, 13.96]  <- IDENTICAL to Run 1
  d02: lat [36.61, 44.00] lon [0.47, 10.76]   <- IDENTICAL to Run 1
```

Both runs completed and produced 25 hourly `wrfout_d01_*`/`wrfout_d02_*`
files with a `SUCCESS` marker, under
`gs://predsea-daily-outputs-test/predictions/{run_date}/runs/{run_id}/`.
Neither run's domain reaches alboran_1km's western edge (lon −6.0°) —
confirmed by direct `XLAT`/`XLONG` inspection, not by trusting the namelist.

### 6.4 WRF image rebuild (fix for 6.3, not yet re-verified)

```text
Cloud Build config: cloudbuild.wrf.yaml (new file, this cycle)
Build ID: a3fac96f-6014-4277-8559-5e7c03a687dd
State at last check: QUEUED
Submitted via: gcloud builds submit --config=cloudbuild.wrf.yaml --async .
```

**First action for the next agent: check this build's current state.** It
was not confirmed complete before this handoff was written. If it succeeded,
proceed to Section 8's step 1 (rerun WRF, re-verify coverage) before
anything else.

## 7. The WRF domain fix — what was actually wrong and what was changed

`simulation/namelist.wps` (the static file at that path) is **not** what the
running pipeline uses — editing it is a no-op, confirmed empirically (Run 2
in 6.3 is byte-identical to Run 1 despite an edit to that file in between).
The real source of truth is `simulation/setup_domain.py`'s `BalearicDomain`
dataclass, which renders the namelist dynamically at container runtime and
is baked into the image via `COPY setup_domain.py
/opt/predsea/setup_domain.py` in `simulation/Dockerfile`. Any domain change
requires an image rebuild, not just a script edit.

The actual fix applied to `simulation/setup_domain.py`:

```python
d01_e_we: int = 210   # was 160
d01_e_sn: int = 140   # was 120
d02_e_we: int = 277   # unchanged
d02_e_sn: int = 271   # unchanged
d02_i_parent_start: int = 65   # was 40
d02_j_parent_start: int = 30   # was 20
```

Reasoning: WRF's Lambert-conformal mother domain (d01) grows symmetrically
about `ref_lat`/`ref_lon` (40.0°N, 5.0°E), so widening d01 from 160×120 to
210×140 columns/rows shifts *both* edges outward by half the added
count (+25 columns, +10 rows on each side). D02 (the finer nest) needed its
`i_parent_start`/`j_parent_start` shifted by that same +25/+10 (in the
parent's own grid-index space) to stay anchored at its original absolute
geographic position over balearic/gulf_of_lion — otherwise fixing d01 would
have silently broken d02's coverage instead. Verified against
`validate_mpi_decomposition()`'s minimum-patch-cell constraints for the
`(8,8)` MPI layout before finalizing (d01: 210/8=26≥10, 140/8=17≥10; d02
unchanged, already passing).

**Not yet re-verified**: whether the new d01 extent actually reaches
alboran_1km's lon −6.0° edge. Do this as soon as the Section 6.4 rebuild
completes — rerun WRF, extract `XLAT`/`XLONG` from the new `wrfout_d01_*`,
and confirm lon_min ≤ −6.0° before trusting the fix.

## 8. Concrete next steps, in order

1. **Check Cloud Build `a3fac96f-6014-4277-8559-5e7c03a687dd`** (Section
   6.4). If still running, wait. If failed, read the build log before
   retrying — do not resubmit blindly.
2. **Rerun WRF for 24h** via `python3 scripts/gcp_orchestrator.py
   --forecast-hours 24` (default `--vm-role wrf`), using the rebuilt image.
3. **Re-verify domain coverage**: extract `XLAT`/`XLONG` from the new
   `wrfout_d01_*` output and confirm the western edge now reaches at least
   lon −6.0° (alboran_1km's bbox minimum). If it still doesn't, the
   parent/child shift arithmetic in Section 7 needs re-derivation, not a
   bigger blind widening.
4. **Build the WRF→WW3 wind adapter** (not started, no code exists yet):
   a script analogous to `wrf_forecast_ingestor.py`'s reading pattern that
   extracts `U10`/`V10` (and `Times`/`XLAT`/`XLONG`) from the confirmed-good
   `wrfout_d02_*` sequence and writes WW3's `ww3_prnc`-expected input format,
   per region (each region will need its own spatial subset/regrid from
   WRF's Lambert grid onto/near that region's WW3 grid — this regridding
   step is new work, not a reuse of anything CROCO's `prepare_croco_forcing.py`
   already does, since that script targets CROCO's grid, not WW3's).
5. **Adapt `ww3_submit_5_region_24h.sh`** (already drafted, using the
   proportional core split from Section 6.1) to consume the new WRF-derived
   per-region wind files instead of the `WIND_GRIB` ECMWF shortcut it
   currently references.
6. **Submit the 24h, 5-region WW3 test** with a generous `maxRunDuration`
   (the 6h test needed up to 2.03h at proportional cores for tyrrhenian; a
   24h run should be budgeted with real headroom, not a naive 4x
   multiplication — measure, don't assume, consistent with
   `docs/ww3-migration-plan-2026-08-04.md`'s general caution against
   unsourced runtime estimates).
7. Only after step 6 passes: consider Phase 3 of
   `docs/ww3-migration-plan-2026-08-04.md` (wiring WW3 into
   `daily_orchestrator.py` as SWAN's replacement) and production cutover
   discussions — both remain explicit later decisions, not implied by a
   passing test.

## 9. Known pitfalls hit this cycle (avoid repeating)

- **macOS ships bash 3.2**: `declare -A` associative arrays silently
  misbehave. Use plain `"key:val:val"` string lists parsed with
  `${entry%%:*}`/`${rest#*:}` parameter expansion in any submission script.
- **Heredoc escaping**: in an unquoted `<<EOF` heredoc, a single backslash
  (`\$!`) is the correct way to pass a literal `$!`/`$LOGGER_PID` through to
  the container's own runtime shell. A double backslash (`\\$!`) evaluates
  `$!` immediately in the outer shell instead, which fails under `set -u`
  since no background job exists yet at heredoc-processing time.
- **GCP Batch job IDs reject underscores**: convert region names via
  `${region//_/-}` (e.g. `algerian_1km` → `algerian-1km`) before using them
  in a job ID — the pattern is `^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$`.
- **`maxRunDuration` hard-kills before any trailing upload**: a job that
  times out uploads nothing unless something is uploading incrementally in
  the background throughout the run (Section 6.2's fix).
- **Custom N2 machine types**: use `n2-custom-<vcpu>-<mem_mib>` with even
  vCPU counts and a 1024 MiB/vCPU ratio for `highcpu`-equivalent sizing —
  applied correctly this cycle for `n2-custom-24-24576` and
  `n2-custom-12-12288`.
- **Everything runs via Cloud Build / GCP Batch / GCE, never local
  Docker** — reaffirmed explicitly this cycle (Section 2a). If you're about
  to type `docker build` or `docker run`, stop and write a
  `cloudbuild.<name>.yaml` instead.

## 10. Required reading

- `docs/ww3-migration-plan-2026-08-04.md` — the original migration plan,
  full SWAN-elimination evidence, and phased rollout (Phases 0–4).
- `docs/whitepaper/02_modeling_suite.md` §5 — whitepaper-level summary of
  this migration (updated alongside this document).
- `docs/agent-handoff-croco-stability-2026-07-22.md` — unrelated CROCO
  stability work; still relevant for the shared conventions (region bounds,
  authorization-boundary style, GCP operating procedure) this document
  follows.

Update this document after every terminal experiment or material design
change. Record evidence (job names, timestamps, exact figures), not
recollections, and clearly separate what's confirmed from what's still a
hypothesis.
