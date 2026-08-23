# PredSea Operational Guide: Bathymetry Integration

This document describes how static bathymetry grids are generated and consumed by the **PredSea CROCO + SWAN forecasting pipeline**. It replaces an earlier version of this doc that described a NEMO-based, Balearic-only architecture — that was never how the deployed pipeline actually worked. The system runs **CROCO** (ocean currents, sea surface height, temperature/salinity) and **SWAN** (waves), not NEMO. There is no NEMO integration anywhere in the live pipeline.

Each of the 5 supported regions (Balearic, Alboran, Gulf of Lion, Tyrrhenian, Algerian) has its own bathymetry grid, generated from EMODnet at that region's native resolution and bounding box.

---

## Generating a region's bathymetry

`scripts/prepare_bathymetry.py` downloads raw bathymetry from the EMODnet Bathymetry Web Coverage Service (WCS), crops/regrids it to a region's domain, and writes a single SWAN-format NetCDF (`depth` on 1D `latitude`/`longitude` coordinates).

```bash
python3 scripts/prepare_bathymetry.py \
  --region alboran_1km \
  --output-dir assets/static_grids \
  --gcs-bucket predsea-daily-outputs-test
```

`--region` reads the bounding box and resolution straight from that region's committed profile at `simulation/marine/regions/{region}.json` (`bbox.longitude_min/max`, `latitude_min/max`, `horizontal_resolution_m`). Large bounding boxes (>16 sq degrees) are automatically tiled and stitched to work around EMODnet's per-request download-size limit.

Output naming: `{region}_bathymetry_swan.nc` locally, uploaded to `gs://{bucket}/static/bathymetry/{region}_bathymetry_swan.nc`. The one exception is Balearic, whose file predates the `--region` flag and is still named `balearic_bathymetry_swan.nc` (no `_1km` suffix) — `run_marine_simulation.py`'s `resolve_swan_bathymetry()` special-cases this region only.

This is normally run once per region via a dedicated Cloud Build job (`cloudbuild.bathymetry.yaml` is a template for this — set the region list and re-run when a region's grid needs regenerating), not as part of the daily/gate pipeline.

---

## How bathymetry reaches the simulation containers

Bathymetry is baked directly into the `croco-batch` Docker image at build time — it is not downloaded at runtime. `simulation/marine/croco/Dockerfile.batch` `COPY`s each region's SWAN bathymetry file from `assets/static_grids/` into `/app/simulation/inputs/` inside the image:

```dockerfile
COPY assets/static_grids/balearic_bathymetry_swan.nc \
     /app/simulation/inputs/balearic_bathymetry_swan.nc
COPY assets/static_grids/alboran_1km_bathymetry_swan.nc \
     /app/simulation/inputs/alboran_1km_bathymetry_swan.nc
COPY assets/static_grids/gulf_of_lion_1km_bathymetry_swan.nc \
     /app/simulation/inputs/gulf_of_lion_1km_bathymetry_swan.nc
COPY assets/static_grids/tyrrhenian_1km_bathymetry_swan.nc \
     /app/simulation/inputs/tyrrhenian_1km_bathymetry_swan.nc
COPY assets/static_grids/algerian_1km_bathymetry_swan.nc \
     /app/simulation/inputs/algerian_1km_bathymetry_swan.nc
```

Consequences of this design:

* All 5 regions' bathymetry files must exist in `assets/static_grids/` **before** rebuilding this image, or the build fails at the `COPY` step.
* `.gcloudignore` has a blanket `**/*.nc` exclusion (needed to keep large output/observation NetCDFs out of Cloud Build source uploads); each region's `*_bathymetry_swan.nc` has an explicit `!`-exception so it still gets uploaded as part of the build context.
* Adding a 6th region means: generate its bathymetry, add its `!`-exception to `.gcloudignore`, add its `COPY` line to `Dockerfile.batch`, and rebuild the image. There is currently no way to add a region's bathymetry without a full image rebuild.
* Since bathymetry is baked in, not downloaded per-run, `vm_startup.sh`/`gsutil` download steps described in older versions of this doc do not apply to bathymetry at all in the current architecture.

At runtime, `run_marine_simulation.py --model=swan --region={region}` calls `resolve_swan_bathymetry(project_root, region_id)`, which looks for `simulation/inputs/{region_id}_bathymetry_swan.nc` inside the container (falling back to `balearic_bathymetry_swan.nc` only for `balearic_1km`). If the file isn't there — e.g. a region added to `regions/` but never given bathymetry, or an image built before that region's `COPY` line was added — the job fails fast with `No versioned SWAN bathymetry is installed for {region}`.

---

## Rebuilding the image after a bathymetry change

`gcloud builds submit --tag ... .` builds the repo-root `Dockerfile`, not `Dockerfile.batch` — there's no way to target a different Dockerfile through that shorthand. Use the dedicated config instead:

```bash
gcloud builds submit --config=cloudbuild.croco-batch.yaml --async .
```

After it succeeds, get the new digest and re-pin it everywhere the image is referenced (`cloudbuild.6h-gate.yaml`'s `_BATCH_IMAGE_URI`, `run_all_regions.sh`, and this doc / the whitepaper if the digest is quoted there):

```bash
gcloud artifacts docker images describe \
  europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch:latest \
  --format="value(image_summary.digest)"
```

`submit_gcp_batch_simulation.py` refuses to submit a real (non-dry-run) Batch job unless `--image-uri` contains an explicit `@sha256:` digest, precisely so a stale mutable `:latest` tag can't silently get used.

---

## Why there's no NEMO bathymetry anymore

`prepare_bathymetry.py` used to also emit a second, NEMO-format NetCDF (`{region}_bathymetry_nemo.nc`, curvilinear `nav_lon`/`nav_lat`/`bathy`) alongside the SWAN one. Nothing in the live pipeline — not `run_marine_simulation.py`, not `resolve_swan_bathymetry()`, not `Dockerfile.batch` — ever read that file. It was vestigial output from an earlier architecture. It has been removed from `prepare_bathymetry.py`; the script now generates and uploads the SWAN NetCDF only.
