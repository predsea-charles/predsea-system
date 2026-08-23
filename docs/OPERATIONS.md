# PredSea Operations & Deployment Runbook

This runbook documents how the CROCO + SWAN forecast pipeline is actually submitted, monitored, and rebuilt, plus the operational guards and past incidents worth knowing about. See `docs/bathymetry-integration-guide.md` for everything specific to generating/rebuilding per-region bathymetry, and `docs/whitepaper/05_cloud_deployment_and_ops.md` for the full architectural writeup.

---

## 1. Regional Deployment Specifications

PredSea operates 5 regional forecast shards across the Western Mediterranean basin, each as a separate CROCO Batch job and a separate SWAN Batch job (never combined — see Section 2):

| Region ID | Grid Points | Machine Type | MPI Ranks | Compute Spec |
| :--- | :---: | :---: | :---: | :---: |
| **`balearic_1km`** | $200,901$ | `c2d-highcpu-16` | 16 | 16 vCPU / 32 GiB |
| **`alboran_1km`** | $124,203$ | `c2d-highcpu-16` | 16 | 16 vCPU / 32 GiB |
| **`gulf_of_lion_1km`** | $121,649$ | `c2d-highcpu-16` | 16 | 16 vCPU / 32 GiB |
| **`tyrrhenian_1km`** | $391,379$ | `c2d-highcpu-16` | 16 | 16 vCPU / 32 GiB |
| **`algerian_1km`** | $282,273$ | `c2d-highcpu-16` | 16 | 16 vCPU / 32 GiB |

The region profiles under `simulation/marine/regions/*.json` are the source of truth for geographic bounds and resolution; `prepare_bathymetry.py --region` and the Batch-sizing logic in `submit_gcp_batch_simulation.py` both read from them.

### Current image

* **Digest-pinned URI**: `europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:f8313ce5d43624d055321ba769f7a7da315c6aad5c7e16c30ab10ba063953ba8` (includes the `PROP BSBT` / stricter open-boundary validation fix in `prepare_swan_run.py`, Gulf of Lion's resized bbox — `latitude_max` 44.5→43.3, recompiled with `LM=498, MM=198` — and a fix in `vtk_to_netcdf.py` where stitched lat/lon coordinate arrays could silently default to 0.0 if an MPI tile's edge wasn't covered, causing a false "doesn't reach boundary" validation failure — the previous image's actual SWAN run for gulf_of_lion_1km completed cleanly in ~14.5 min, so this fix is expected but not yet re-confirmed end-to-end with this image. Alboran/algerian still stall before producing any timestep output — separate, unresolved issue, likely SWAN's own wet-point-balanced domain decomposition struggling with their irregular coastlines — see SWAN slow-convergence investigation notes)

This digest is what `cloudbuild.6h-gate.yaml` and `run_all_regions.sh` are pinned to. Whenever the image is rebuilt (new bathymetry, new binaries, dependency bump), the digest changes and every reference to the old one must be updated — see "Rebuilding the image" in `docs/bathymetry-integration-guide.md`.

---

## 2. Running the pipeline

### The real gate: WRF → CROCO → SWAN, all 5 regions

The actual pipeline is submitted as a single Cloud Build job, not run locally:

```bash
gcloud builds submit --config=cloudbuild.6h-gate.yaml --async .
```

This invokes `scripts/daily_orchestrator.py --use-gcp-batch`, which:

1. Fetches ECMWF/CMEMS boundary forcing (credentials come from Secret Manager, not a local `.env` — see the comment block at the top of `cloudbuild.6h-gate.yaml` for the exact IAM binding needed).
2. Runs WRF once on a shared VM (atmospheric forcing for all regions).
3. Submits CROCO as a Batch job for every region in `_BATCH_REGIONS` simultaneously, and waits for all of them.
4. Only after CROCO succeeds everywhere, submits SWAN the same way as a second phase.

`_FORECAST_HOURS`, `_BATCH_REGIONS`, `_BATCH_IMAGE_URI`, and `_GCS_BUCKET` in `cloudbuild.6h-gate.yaml`'s `substitutions` block control the horizon, region list, image digest, and output bucket. **Only run one Cloud Build pipeline like this at a time** — two concurrent WRF VMs (64 vCPU each) can exhaust the project's Compute quota on their own.

Track it:

```bash
gcloud builds describe <build-id> --format="value(status)"
gcloud builds log <build-id> --stream            # live tail
```

Once the orchestrator gets past WRF and starts submitting Batch jobs:

```bash
gcloud batch jobs list --location=europe-west1 --format="table(name,status.state)"
gcloud batch jobs describe <job-id> --location=europe-west1 --format="value(status.statusEvents)"
```

The `status.statusEvents` output (not `gcloud logging read resource.type=batch_job` — that resource type has no entries) is the reliable way to get a real exit code and truncated `stderr_snippet` for a failed job.

### Ad-hoc single-region runs

`run_all_regions.sh` submits standalone 72h CROCO-only jobs per region directly via `submit_gcp_batch_simulation.py`, bypassing the orchestrator (no WRF step, no SWAN). Useful for isolating a single region's CROCO behavior, not a substitute for the real gate.

---

## 3. Post-Mortem Analysis & System Operational Guards

### Incident: Staggered C-Grid Validation OOM
* **Symptom**: GCP Batch simulation runs failed during post-processing with `RuntimeError: CROCO content validation failed with exit code 1`.
* **Root Cause**: `scripts/validate_marine_output.py` applied `mask_rho` to staggered velocity fields (`u` on `eta_u, xi_u` and `v` on `eta_v, xi_v`). `xarray` attempted an outer join of unmatched dimensions on a 3D ocean domain, attempting to allocate 250+ TB of RAM.
* **Fix**: `_apply_matching_mask` in `scripts/validate_marine_output.py` now matches mask grid dimensions (`mask_u` for `u`, `mask_v` for `v`, `mask_rho` for `temp/salt/zeta`).
* **Verification**: Validation dropped from an OOM hang to ~1.8 seconds, returning `"status": "succeeded"`.

### Incident: SWAN never worked for any region, including Balearic
* **Symptom**: Every SWAN Batch job, for every region, failed with `No versioned SWAN bathymetry is installed for {region}`.
* **Root Cause**: the actually-deployed `croco-batch` image (built from `simulation/marine/croco/Dockerfile.batch`) never compiled SWAN or baked in any bathymetry. A separate, never-merged `simulation/marine/swan/Dockerfile.batch` did both, but was not the image referenced by any real submission.
* **Fix**: merged the SWAN build stage into `Dockerfile.batch`, generated bathymetry for the 4 regions that didn't have it, and baked all 5 regions' SWAN bathymetry into the final image stage. Rebuilt and re-pinned the digest everywhere (Section 1).
* **Status**: fixed and image rebuilt; superseded by the cross-region cache collision below as the next thing that broke once SWAN actually started running for all 5 regions.

### Incident: cross-region CMEMS forcing cache collision (SWAN crash, CROCO silent-corruption risk)
* **Symptom**: SWAN Batch jobs for `alboran_1km` and `gulf_of_lion_1km` failed with `ValueError: south wave boundary has no finite values at index 0` in `prepare_swan_run.py`, while other regions' SWAN jobs succeeded.
* **Root Cause**: `fetch_native_marine_forcing.py` always writes a region's fetched CMEMS wave-boundary data to the same fixed filename (`cmems_swan_boundary.nc`), and `run_marine_simulation.py` cached/uploaded it to a GCS path keyed only by `run_date` (`forcing/cmems/{run_date}/`), not by region. With all 5 regions' SWAN jobs submitted in parallel, whichever region's job populated that shared cache first caused every other region to silently reuse its (wrong-bbox) wave data. SWAN's `_side_series` validation caught this as a crash because the wrong region's boundary data was all-NaN at the edge it checked. **CROCO has the identical design flaw in its own CMEMS cache-reuse check (`staged_products`/`staged_cmems`), but no equivalent runtime check that would catch wrong-region ocean forcing — it would have run to completion producing silently invalid physics rather than failing.** Not confirmed to have actually fired for CROCO in any specific past run (no evidence checked), but the vulnerable code path existed.
* **Fix**: both the SWAN wave-boundary cache (local file + GCS object) and CROCO's 4 CMEMS product caches (`cmems_croco_currents_3d/temperature_3d/salinity_3d/sea_level`) are now scoped by region in their filenames (e.g. `cmems_swan_boundary_{region}.nc`), so parallel regions sharing the same run_date's cache directory can never read each other's forcing data.
* **Status**: fix implemented in `scripts/run_marine_simulation.py`; not yet confirmed by a clean end-to-end gate run.

### Incident: coastal region boundary edge entirely on land (Gulf of Lion, north side)
* **Symptom**: After the cache-collision fix above, `gulf_of_lion_1km`'s SWAN job still failed with `ValueError: north wave boundary has no finite values at index 0`, using its own correctly-scoped, region-specific wave data.
* **Root Cause**: `gulf_of_lion_1km`'s bbox northern edge (latitude 44.5°N, plus the 0.5° CMEMS fetch buffer) sits well past the real French Mediterranean coastline (~43.5–43.7°N in that longitude band) — essentially inland. CMEMS's wave product is masked (NaN) over land, so the entire north edge row had zero ocean cells. This isn't unique to this region or this resolution: any bbox with a coastal/bay-shaped edge can end up entirely land-masked, and it becomes more likely, not less, as resolution increases and bboxes get drawn tighter to a coast.
* **Fix**: `_side_series` in `scripts/prepare_swan_run.py` no longer treats an all-NaN boundary edge as fatal. It now walks inward from the true edge, row by row (or column by column), until it finds the nearest row/column with real ocean data, and uses that as the boundary condition — logging how many cells inward it had to go. Only raises if literally no row/column along that entire axis has any ocean data at all (i.e. the region doesn't reach open water on that side under any circumstances).
* **Status**: implemented; requires an image rebuild (this file is baked into `croco-batch` via `Dockerfile.batch`'s `COPY scripts /app/scripts`) before it takes effect.

### Local Footprint & In-Cloud Policy
1. **Zero Local Dataset Downloads**: Operators and developers should not download multi-gigabyte forecast NetCDF files to local workstations.
2. **Streaming Inspection**: Use `xarray` with `gcsfs` for remote metadata and slice inspection.
3. **Containerized Execution**: All pre-processing, model execution, and validation routines run inside GCP Batch containers.
