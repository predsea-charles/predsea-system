# PredSea SWAN Strategy — Basin-Wide Architecture, Status, and WW3 Contingency

Last updated: **2026-08-03 (Europe/Madrid)**
Repository: `/Users/charles.santana/PredSea/predsea-system`
Google Cloud project: `predsea-api`
Bucket in use for all work described here: `predsea-daily-outputs-test` (production untouched)

This document summarizes why the current SWAN architecture exists, what has
been tested and learned so far, the decision framework for what happens next,
and WaveWatch III (WW3) as the contingency path if the current approach turns
out not to be viable. It is written as a snapshot, not a continuation
contract — read the linked scripts/configs for exact current state.

## 1. The original problem

Per-region SWAN runs (one small domain per region, run as a GCP Batch job)
work fine for 2 of 5 regions (`balearic_1km`, `tyrrhenian_1km`) but fail for
3 (`alboran_1km`, `gulf_of_lion_1km`, `algerian_1km`). The diagnosed root
cause: bathymetry data quality — some grid cells in these 3 regions are
misclassified as land when they are actually water (or vice versa), which
produces degenerate SWAN domain decompositions and crashes. This has not
been root-caused at the data level (no one has yet compared the generated
bathymetry masks against an authoritative coastline dataset to find and fix
the specific bad cells).

## 2. Current strategy: basin-wide SWAN

Rather than fixing the bathymetry data directly, the current approach runs
SWAN **once**, over the union bounding box of all 5 regions (`med_basin_1km`
region profile), instead of 5 separate small-domain jobs. The hypothesis:
folding all 5 regions into one large, mostly-open-sea domain dilutes the
narrow/irregular coastline features that cause the crash, without needing to
know exactly what is wrong with the source bathymetry data.

### Architecture

Three strictly sequential stages, each on its own compute allocation, so no
two stages ever compete for the project's 64-vCPU `CPUS_ALL_REGIONS` quota
at the same time:

```text
WRF VM (n2-standard-64) --> self-deletes on success
        |
        v
basin-SWAN VM (n2-standard-64, 64 MPI ranks) --> self-deletes on success
        |
        v
CROCO Batch jobs (5 regions, throttled to 4 concurrent x 16 vCPU)
```

- WRF and basin-SWAN run on dedicated, ephemeral GCE VMs (`gcp_orchestrator.py
  --vm-role=wrf` / `--vm-role=basin-swan`), launched and polled by
  `daily_orchestrator.py`.
- Basin-SWAN is **non-fatal**: if it fails or times out, CROCO's Batch jobs
  still run, since CROCO does not depend on SWAN's output.
- The basin-wide SWAN output is cropped back into the 5 regions' expected
  file layout by `scripts/crop_basin_swan_output.py`, so nothing downstream
  (ingestors, validation, product API) needs to change.
- When `_BASIN_SWAN_REGION` is set, **all 5 regions** source their wave
  product from this one basin-wide pass — `balearic_1km`/`tyrrhenian_1km` no
  longer run their own per-region SWAN jobs, even though those used to work
  fine at 1km. This was a deliberate decision (see §4): a per-region-resolution
  split (2 regions at 1km, 3 at coarser resolution) was considered and
  rejected as inconsistent.

## 3. What's been tested, and what it showed

| Test | Resolution | Timestep | Physics | Ranks | Result |
|---|---|---|---|---|---|
| 1 | 1km (~1.8-2.3M pts) | 5 min | GEN3 WESTHUYSEN | 32 | Still running after 8+h, called off as impractical |
| 2 | 1km | 5 min | GEN3 WESTHUYSEN | 64 | Stuck at first hourly output block for 7h44m+, killed |
| 3 | 1km | 5 min | GEN3 KOMEN | 64 | Stuck at first hourly output block for 10h32m+, died to an infra/docker fault |
| 4 | 3km (9x fewer pts) | 10 min | GEN3 KOMEN | 64 | In progress as of this writing |

Key findings so far:

- **Basin-wide SWAN reliably avoids the original crash.** Across every test
  above, there has been no repeat of the small-region crash. This confirms
  the core hypothesis (diluting narrow coastlines into a large domain avoids
  the degenerate-decomposition problem), independent of the speed problem
  below.
- **Physics scheme is not the bottleneck.** Swapping `GEN3 WESTHUYSEN` for
  the cheaper `GEN3 KOMEN` source-term formulation made no measurable
  difference — both got stuck at the same milestone (first hourly output
  block) for similar or longer durations.
- **Raw rank count is not the (whole) bottleneck either.** Doubling MPI
  ranks from 32 to 64 did not proportionally reduce runtime — if anything,
  the 64-rank runs took as long or longer to reach the same milestone. This
  points at something structural (e.g. load imbalance from SWAN's
  wet-point-count-based domain decomposition not accounting for actual
  per-cell computational cost, or MPI communication overhead scaling badly
  for this domain's size/shape) rather than simple insufficient throughput.
- Test 4 (3km resolution + 10-minute timestep, both changed together) is the
  first test targeting **raw problem size** directly, which is the leading
  remaining hypothesis. Result pending.

### A process bug found and fixed along the way

`Dockerfile.batch` bakes the region JSON profiles and bathymetry `.nc` files
into the `croco-batch` image at **build time** via `COPY` — they are not
read live from GCS or the repo at runtime. Two of today's test attempts
silently ran the *original* 1km/5-minute config despite editing
`med_basin_1km.json`, because the image had not been rebuilt, and because a
regenerated bathymetry file had landed in the wrong local directory
(`simulation/inputs/` instead of `assets/static_grids/`, which is what the
Dockerfile actually copies from). Any future change to a region profile or
its bathymetry **must** be followed by: regenerating the bathymetry into
`assets/static_grids/`, rebuilding `cloudbuild.croco-batch.yaml`, updating
`cloudbuild.6h-gate.yaml`'s `_BATCH_IMAGE_URI`/`_BASIN_SWAN_IMAGE_URI` to the
new digest, and — critically — verifying the baked-in file's actual grid
size via `docker create`/`docker cp` before trusting a test run. Do not
trust the JSON profile alone; verify the actual baked-in bathymetry file.

A second, unrelated bug fixed in passing: `balearic_1km` had never had a
correctly-named bathymetry file generated (`cloudbuild.bathymetry.yaml`'s
region loop omitted it); it was silently falling back to a mislabeled file
that actually covered the whole basin extent. Fixed by generating the
correct file, adding `balearic_1km` to the generation loop, and removing the
now-dead fallback in `scripts/run_marine_simulation.py`.

## 4. Decision framework for the current test (Test 4)

- **Great outcome**: clears all 6 hourly output blocks in ~1-2 hours total.
  Real headroom under the 12h basin-SWAN timeout; treat basin-wide SWAN as
  viable and move toward production use / longer forecast horizons.
- **Good outcome**: completes, but takes several hours (3-8h). Confirms the
  resolution/timestep hypothesis directionally, but leaves little margin
  under the 24h pipeline ceiling — worth further tuning before relying on it
  for longer (24-72h) forecasts.
- **Bad outcome**: still stuck at or near the first output block many hours
  in, similar to Tests 2-3. Would mean a 9x grid cut plus doubled timestep
  wasn't enough, pointing strongly at the structural
  (load-imbalance/decomposition) hypothesis rather than raw problem size.

A per-region-resolution split (keep `balearic_1km`/`tyrrhenian_1km` on their
own working 1km per-region Batch jobs, only route the 3 broken regions
through the coarser basin-wide path) was explicitly discussed and rejected:
all 5 regions must share one uniform resolution for consistency, so a Good
or Great outcome commits all 5 regions to whatever resolution made the
basin-wide approach work (currently 3km, down from 1km for `balearic`/
`tyrrhenian` specifically).

## 5. Next steps if Test 4 is a Bad outcome

1. **Confirm the load-imbalance hypothesis directly**, if a future test run
   is still live: SSH in and compare per-MPI-rank accumulated CPU time
   (`ps -eo pid,pcpu,time,comm --sort=-time`) against wall-clock elapsed. If
   some ranks show far less accumulated CPU time than others despite all
   showing ~100% instantaneous CPU (possible with MPI busy-wait polling),
   that confirms a straggler rank rather than genuine uniform compute cost.
2. **Consider fixing the root cause instead of working around it**: compare
   the 3 broken regions' generated bathymetry wet/dry masks against a real
   coastline reference (e.g. GSHHG) to find and fix the actual misclassified
   cells, restoring all 5 regions to their own fast, small, per-region 1km
   SWAN jobs and retiring the entire basin-wide architecture.
3. **Migrate to WaveWatch III (WW3)** — see §6.

## 6. WW3 as contingency

If the structural bottleneck is confirmed (or if fixing the bathymetry data
directly doesn't fully resolve things), WaveWatch III is the most credible
alternative model, raised in an external review of this problem:

- WW3 uses explicit propagation schemes suited to open-ocean/basin-scale
  domains, rather than SWAN's implicit scheme, which is optimized for
  shallow coastal zones and becomes comparatively expensive over large
  deep-water areas.
- CROCO has native coupling support for WW3 via OASIS-MCT, which could allow
  genuine two-way wave-current interaction (Stokes drift, orbital
  velocities, surface stress) rather than the current one-way setup.
- A hybrid design is possible: one basin-scale WW3 domain for open water,
  with small nested SWAN grids retained only for ultra-fine nearshore/port
  detail if ever needed.

This is a **major undertaking**, not a quick fix: it means a new Docker
image, a different input file format and preparation pipeline, no existing
PredSea code to build on, and a full validation pass against the current
SWAN-based baseline before trusting it operationally. It should only be
pursued if the current basin-wide SWAN approach (Test 4 onward) and a direct
bathymetry-data fix both prove impractical — not adopted reflexively.

Some specific technical claims from that external review do not match this
codebase's actual configuration and should not be applied uncritically if
revisited later: this pipeline already runs `MODE NONSTATIONARY` (not
`STATIONARY`) and already uses `PROP BSBT` specifically for robustness across
steep bathymetric transitions — two of the review's suggested "fixes" are
already in place. Its suggested `NUMERICS ACCUR ... STAT ...` command also
targets stationary-mode parameters that don't apply to this nonstationary
configuration; per SWAN's own documentation, nonstationary runs already
default to a maximum of 1 iteration per timestep, so there is little room to
"loosen convergence" further in the way that command implies.

## 7. Other open items (not blocking, but tracked)

- **Copernicus credentials are passed in plaintext** through
  `gcp_orchestrator.py`'s printed `gcloud compute instances create` command,
  which lands in Cloud Build logs in cleartext. Worth a redaction fix and a
  password rotation, independent of the SWAN work above.
- **An unexplained VM/docker-daemon failure pattern** has occurred twice
  (both times the basin-SWAN VM died with an identical `grpc: context
  canceled` / exit-125 error, and both times the VM was fully deleted rather
  than left `TERMINATED` per its own failure-handling logic, contrary to
  what the script's cleanup trap should do on a non-zero exit). One
  occurrence was later explained (a deliberate `gcloud compute instances
  delete` we issued); the earlier one remains unexplained. Worth
  investigating via GCE audit logs if it recurs on a run nobody deliberately
  killed.
