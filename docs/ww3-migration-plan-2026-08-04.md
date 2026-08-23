# WaveWatch III (WW3) Migration Plan — Full Replacement of SWAN

Last updated: **2026-08-04 (Europe/Madrid)**
Repository: `/Users/charles.santana/PredSea/predsea-system`
Google Cloud project: `predsea-api`
Bucket in use for all work described here: `predsea-daily-outputs-test` (production untouched)

Supersedes the "WW3 as contingency" section of `docs/swan-basin-wide-strategy-2026-08-03.md`
now that the contingency has been triggered. This is a plan for **full
replacement** of SWAN with WW3 across all 5 regions (`alboran_1km`,
`gulf_of_lion_1km`, `balearic_1km`, `tyrrhenian_1km`, `algerian_1km`), not a
hybrid — decided 2026-08-04 to keep one uniform solver/architecture across
regions, consistent with the earlier decision to keep resolution uniform.

## 1. Why: what today's test proved

Basin-wide SWAN was built to work around 3 regions (`alboran`, `gulf_of_lion`,
`algerian`) failing in small-domain per-region runs, on the assumption the
cause was bathymetry land/water misclassification. Over the past two days,
every plausible fix was tried and ruled out in order:

- **Bathymetry data quality**: validated all 5 regions' generated bathymetry
  against GSHHG ground truth. Mismatch is 0.3-0.8% everywhere, no worse for
  the broken regions than the working ones. Not the cause.
- **Resolution / timestep**: 1km/5min -> 3km/10min made no difference to the
  basin-wide non-convergence.
- **Physics scheme**: GEN3 WESTHUYSEN vs. GEN3 KOMEN made no difference.
- **Rank count / load imbalance**: 32 -> 64 ranks made no difference; CPU
  time is perfectly even across all ranks in every test (no straggler).
- **Domain size** (today's decisive test): a standalone `alboran_1km`
  per-region SWAN Batch job (155k grid points, 16 ranks — nowhere near
  basin-wide's scale) hit the **identical** "stuck at output request 1"
  non-convergence, 1h46m in, evenly loaded across all ranks. This ruled out
  "just go back to fast per-region jobs" as a fix, since the tiny native
  domain fails exactly like the giant merged one.

Five independent variables tried, zero fixes. The evidence points at
something structural to SWAN's implicit solver on this specific combination
of coastline/bathymetry geometry (shared by alboran/gulf_of_lion/algerian,
and inherited by any basin domain that contains them) rather than anything
tunable in this codebase.

## 2. Why WW3 specifically

WW3 uses an **explicit** propagation scheme, built for basin/ocean-scale
domains — the opposite design point from SWAN's implicit solver, which is
optimized for small, shallow coastal domains and becomes both numerically
harder and comparatively more expensive as domain size and coastline
complexity grow. This is a different algorithmic path through the same
physics, not a parameter change, so it isn't subject to the same failure
mode we've now ruled every tunable knob out for.

## 3. What's already reusable vs. what must be built

The surrounding infrastructure is mostly solver-agnostic and carries over
directly. The parts that don't are SWAN-specific input/output plumbing.

### Reusable as-is
- **GCS layout and run_date/run_id conventions** (`gs://predsea-daily-outputs-test/predictions/{run_date}/runs/{run_id}/...`,
  `forcing/{ecmwf,cmems}/{run_date}/...`) — solver-agnostic.
- **BigQuery `evidence_rows` schema** (`humanintheloop/bigquery_export.py`) —
  already keyed by `provider` (e.g. `predsea_swan`), not hardcoded to SWAN.
  WW3 just becomes a new provider value (`predsea_ww3`); no schema change.
- **API blending logic** (`humanintheloop/api/app.py`'s priority-ranked
  BigQuery query) — already provider-agnostic; just needs `predsea_ww3`
  added to the priority-rank CASE statement in place of/alongside
  `predsea_swan`.
- **Region JSON profile schema** (`simulation/marine/regions/*.json`) — bbox,
  resolution, and `models_enabled` structure carry over; only the
  `models.swan` block's contents are solver-specific and need a
  `models.ww3` equivalent.
- **Orchestrator/Batch throttling architecture** (`daily_orchestrator.py`,
  `submit_gcp_batch_simulation.py`, the 3-stage WRF -> wave -> CROCO
  sequencing, the 64-vCPU quota throttling) — this is solver-agnostic
  infrastructure and needs no rework, only new image URIs/model flags.
- **Docker multi-stage build pattern** — `Dockerfile.batch` already builds
  SWAN from source in a dedicated builder stage (`swan_builder`, pinned
  version + SHA256 checksum) and copies the compiled binary into the final
  image. WW3 follows the identical pattern (build from NOAA-EMC/WW3 source
  in its own builder stage).
- **CROCO's own OASIS-MCT coupling toolbox**: the vendored CROCO source
  already ships an OASIS coupling toolbox (`SCRIPTS_COUPLING/SCRIPTS_TOOLBOX/OASIS_SCRIPTS/`,
  seen under `tmp/croco-v2.1.3/` and `tmp/croco_build/croco_src/`), currently
  unused by this pipeline (today's SWAN->CROCO coupling is one-way file
  handoff, not true OASIS coupling). This meaningfully de-risks a future
  two-way WW3<->CROCO coupling phase, since the scaffolding already exists
  in the CROCO distribution we're already using — it isn't a from-scratch
  integration.
- **Validation approach**: the existing forecast-vs-observation validation
  script (built earlier this project) can be reused directly for
  forecast-vs-forecast comparison (WW3 output vs. the current SWAN
  baseline) before trusting WW3 operationally.

### Must be built new (SWAN-specific, no equivalent exists yet)
- **WW3 build stage** in `Dockerfile.batch` (or a new `Dockerfile.ww3-batch`):
  compile WW3 from source (NOAA-EMC/WW3 on GitHub), MPI-enabled, with a
  compile-time "switch" file selecting the physics package (ST4/Ardhuin et
  al. is the modern default), propagation scheme, and output modules. This
  is a compile-time configuration step SWAN doesn't have (SWAN's equivalent
  choices are runtime `.swn` command file directives) — worth getting right
  once rather than iterating via rebuilds.
- **Grid generation**: WW3's native grid definition (`ww3_grid` preprocessor)
  replaces `prepare_bathymetry.py`'s SWAN-specific NetCDF output. Needs a
  new script analogous to `prepare_bathymetry.py` that emits WW3's expected
  grid/bathymetry input format for each region's bbox.
- **Forcing preprocessing**: WW3's `ww3_prnc` preprocessor converts wind and
  (if applicable) current fields from NetCDF into WW3's native binary
  forcing format. Replaces the ECMWF-wind-to-SWAN-`.dat` conversion
  currently done in `prepare_swan_run.py`.
- **Boundary conditions**: if any region needs nested/telescoped grids,
  `ww3_bounc` generates boundary spectra from a parent grid — otherwise a
  single basin-scale WW3 domain may not need per-region boundary files at
  all (unlike SWAN's per-region TPAR boundary files), which is a
  structural simplification worth confirming early.
- **Output post-processing**: `ww3_ounf` writes WW3's native binary output
  directly to NetCDF, in contrast to the current pipeline's SWAN-specific
  detour (`native_output.format: parallel_vtk` -> `vtk_to_netcdf.py` ->
  `crop_basin_swan_output.py`), which exists specifically to work around
  "SWAN MPI NetCDF shard collection failure." This entire detour likely
  isn't needed for WW3 and can probably be retired, simplifying the output
  pipeline.
- **Region profile schema extension**: add a `models.ww3` block to each
  region JSON (directions/frequencies/timestep equivalents, physics package
  selection) alongside or replacing `models.swan`.

## 4. Phased rollout

1. **Phase 0 — standalone build + smoke test on one working region.**
   Build the WW3 image, generate a grid for `tyrrhenian_1km` or
   `balearic_1km` (deliberately *not* one of the 3 broken regions — we want
   a region with a known-good SWAN baseline to validate against, not one
   where "did it work" is ambiguous), and confirm WW3 runs to completion
   and produces sane `Hs`/`Tp`/`Dir` output at all.
2. **Phase 1 — validate against the SWAN baseline.** Run WW3 and SWAN
   side-by-side for the same region/forecast cycle; compare using the
   existing forecast-vs-observation validation script (extended to also do
   forecast-vs-forecast). Confirm WW3's output is physically comparable
   (not necessarily identical) to SWAN's on a region where SWAN is known to
   work correctly.
3. **Phase 2 — the actual target: the 3 broken regions.** Generate WW3
   grids for `alboran_1km`, `gulf_of_lion_1km`, `algerian_1km` and confirm
   they converge and complete — this is the entire point of the migration,
   and the first real evidence the decision was correct.
4. **Phase 3 — full basin integration.** Wire WW3 into
   `daily_orchestrator.py` as a replacement for both the per-region SWAN
   Batch jobs and the basin-wide SWAN VM step, across all 5 regions
   uniformly. Retire `med_basin_1km.json`, the basin-wide VM stage, and the
   VTK-to-NetCDF cropping detour once WW3 is confirmed stable.
5. **Phase 4 (future, optional) — two-way OASIS-MCT coupling with CROCO.**
   Not required for parity with the current one-way setup, but worth
   revisiting given CROCO's existing OASIS toolbox — would allow genuine
   wave-current interaction (Stokes drift, orbital velocities, surface
   stress) rather than the current one-way forcing handoff.

Production cutover (switching the real daily pipeline, not just the test
bucket) should not happen before Phase 2 is validated and Phase 3 is stable
for at least several consecutive daily test-bucket runs.

## 5. Honest effort estimate

This is weeks, not days — consistent with what was flagged when WW3 was
first raised as a contingency. What's changed since then is the confidence
level: a large share of the surrounding infrastructure (GCS/BigQuery/API/
orchestrator/Docker patterns, and CROCO's own OASIS scaffolding) is
directly reusable, so the real new work is concentrated in WW3-specific
grid generation, forcing preprocessing, and the compile-time build
configuration — not a rebuild of the entire pipeline end to end.

## 6. Open questions to resolve early in Phase 0

- Does a single basin-scale WW3 domain need any nesting/boundary files at
  all, or can one domain cover all 5 regions' bboxes without the
  per-region boundary complexity SWAN required? (If yes, this removes an
  entire category of "must build" work above.)
- Which physics package (ST4 vs. ST6) is appropriate for the Western
  Mediterranean's wave climate — worth a literature/community check during
  Phase 0 rather than defaulting blindly.
- Confirm WW3's licensing/distribution terms are compatible with this
  project's deployment model before building on it operationally (it's
  NOAA/IFREMER community software; worth a quick confirmation, not assumed).

## 7. 2026-08-04 addendum: decisions locked in after external review

A second round of external AI feedback proposed skipping straight to a
single unified 1km Western-Med WW3 domain as the *first* Phase 0 test, on
the basis of a specific runtime claim ("~1.2M points, 120h forecast in
~30-60 minutes on 64 vCPUs") graded against a "5-hour daily execution SLA."
Both of those specifics were checked against this repo and rejected:

- **No "5-hour SLA" exists anywhere in this project's documentation.**
  Actual documented pipeline budgets are far more generous: an older
  whitepaper doc describes a 12-14h combined WRF+Batch budget, and the
  current `cloudbuild.6h-gate.yaml` timeout is 24h. Any future runtime
  claim should be benchmarked against these real, sourced numbers, not an
  unsourced "5 hours."
- **The "~30-60 minute" runtime figure is unsubstantiated** — no citation,
  and WW3 runtime depends heavily on grid type, physics package, output
  frequency, and actual hardware. Treat it as a hypothesis Phase 0 must
  measure, not a planning assumption.
- **Jumping straight to the full unified domain as the first test repeats
  the exact mistake that cost days on basin-wide SWAN**: build the
  biggest, slowest-to-iterate system first, then discover slowly whether
  it works. Phase 0 stays as originally planned — a smaller, known-good
  region first (`tyrrhenian_1km` or `balearic_1km`), not the full basin.
- **CFL timestep must not be hardcoded.** A proposed `Δt = 30-45s` range
  was plausible-sounding but asserted with false precision. WW3's own
  `ww3_grid` preprocessor computes the governing CFL-limited timestep from
  actual grid spacing and bathymetry — this must come out of Phase 0's
  grid generation, not be assumed beforehand.

What *is* confirmed and locked in from that review: ST4 (Ardhuin et al.,
2010) as the compile-time physics package default; no per-region nesting
needed for the unified-domain target architecture (crop downstream
instead, reusing `crop_basin_swan_output.py`/cdo/nco patterns); WW3's
public-domain NOAA licensing is compatible with commercial downstream use
(still worth an actual license-file read during the Docker build step, not
just taken on reputation); and `ww3_ounf` output feeding `evidence_rows`
under `provider='predsea_ww3'` needs no schema change, confirmed to leave
the API and WhatsApp-facing layers (`docs/api-whatsapp.md`) untouched.

**Concrete Phase 0 next steps, in order:**
1. Build `Dockerfile.ww3-batch` (WW3 from source, MPI-enabled, `ST4` switch
   pre-selected). Done 2026-08-04, build `9063a3e8` submitted.
2. Run `ww3_grid` for `alboran_1km` first (not `tyrrhenian_1km` as
   originally written above) — reordered 2026-08-04. This is a smaller
   bbox than `tyrrhenian_1km` (12.5 vs. 42.25 sq deg), so it is not a
   scale-escalation risk like the rejected "start with the full unified
   basin" idea; it directly tests the region that actually motivated this
   migration, rather than spending a cycle proving WW3 works on a region
   we didn't need it to fix. If `alboran_1km` fails with an obvious
   config-level error (namelist parse failure, crash), that's almost
   certainly our setup and doesn't need a baseline to diagnose. If it
   instead reproduces the exact SWAN symptom (stuck at the first output
   step, no crash, even CPU load across ranks), that's the ambiguous case
   where `tyrrhenian_1km`/`balearic_1km` become the necessary control test
   — run one of them next specifically to tell "our config is wrong" apart
   from "WW3 hits the same wall SWAN did."
3. Run the Phase 0 smoke test on `alboran_1km`; measure actual execution
   time per forecast hour on the target GCP vCPU configuration, and
   confirm sane `Hs`/`Tp`/`Dir` output, before any decision to scale to the
   full unified domain.
