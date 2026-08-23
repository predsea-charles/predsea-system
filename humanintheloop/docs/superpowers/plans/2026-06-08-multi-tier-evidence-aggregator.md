# Multi-Tier Evidence Aggregator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Phase 1 multi-tier evidence architecture that can represent atmospheric provider priority, blend wind-grid and ocean-grid evidence, and expose source lineage to the Co-Captain without making production ETL depend on fragile new endpoints.

**Architecture:** Add a provider-normalization layer for wind forecasts, a grid blending layer using `xarray.Dataset.interp`, and a lineage layer in evidence packages. Phase 1 uses deterministic provider stubs/metadata and local datasets so tests and production remain stable while credentials and exact endpoints are confirmed.

**Tech Stack:** Python, xarray, NetCDF, pytest, JSON evidence packages, existing PredSea route/API modules.

---

## File Structure

- Create `ingest_atmosphere.py`: defines atmospheric provider priorities, normalized wind source metadata, fallback selection, and future fetcher boundaries.
- Create `grid_blender.py`: aligns Copernicus ocean variables to the active wind grid using xarray interpolation and returns merged datasets plus lineage.
- Create `test_ingest_atmosphere.py`: tests tier priority, fallback behavior, and source metadata.
- Create `test_grid_blender.py`: tests interpolation/merge behavior on small synthetic xarray datasets.
- Modify `evidence_package.py`: adds `evidence_package_id` and `data_lineage` to every route evidence JSON.
- Modify `briefing_renderers.py` or `decision_engine.py`: adds source-aware wording for high-resolution wind vs fallback wind.
- Modify `forecast_sources.py`: keeps SOCIB model forecasts disabled from production source selection while preserving the code path for future experimental use.

## Task 1: Atmospheric Provider Interface

- [x] Write failing tests in `test_ingest_atmosphere.py`:
  - AROME success wins over AEMET/ECMWF.
  - AROME failure falls back to AEMET.
  - AROME+AEMET failure falls back to ECMWF.
  - All failures return unavailable lineage instead of raising.
- [x] Implement `ingest_atmosphere.py` with:
  - `BALEARIC_BBOX = {"south": 38.0, "north": 40.5, "west": 1.0, "east": 4.5}`
  - provider definitions for `meteo_france_arome`, `aemet_harmonie_arome`, `ecmwf_open_data`
  - `select_wind_forecast(fetchers, bbox=BALEARIC_BBOX)`
  - `lineage_for_wind_result(result)`
- [x] Run `pytest test_ingest_atmosphere.py`.

## Task 2: Grid Blender

- [x] Write failing tests in `test_grid_blender.py` using tiny synthetic xarray datasets:
  - ocean variables interpolate onto wind latitude/longitude grid.
  - merged dataset keeps wind variables and interpolated ocean variables.
  - lineage marks ocean status as `interpolated_to_wind_grid`.
- [x] Implement `grid_blender.py` with:
  - `standard_lat_lon_names(ds)`
  - `interpolate_ocean_to_wind_grid(ocean_ds, wind_ds)`
  - `blend_wind_and_ocean(wind_ds, ocean_ds, wind_lineage, ocean_lineage)`
- [x] Run `pytest test_grid_blender.py`.

## Task 3: Evidence Lineage Schema

- [x] Write failing test in `test_evidence_package.py`:
  - route evidence package includes `evidence_package_id`.
  - route evidence package includes `data_lineage.wind_forecast`, `ocean_forecast`, and `ground_truth_validation`.
- [x] Modify `evidence_package.py` to derive lineage from `snapshot["data_lineage"]`, defaulting to Copernicus + SOCIB observations when missing.
- [x] Run `pytest test_evidence_package.py`.

## Task 4: Source-Aware Co-Captain Wording

- [x] Write failing tests in `test_decision_engine.py` or a focused renderer test:
  - AROME lineage produces precise high-resolution coastal wording.
  - ECMWF fallback lineage produces softer coastal wording.
- [x] Implement a small helper, preferably in `decision_engine.py`, such as `render_lineage_guidance(snapshot)`.
- [x] Ensure the answer includes the guidance only when relevant and does not overstate confidence.
- [x] Run the focused test file.

## Task 5: Production Source Selection Cleanup

- [x] Write failing test in `test_forecast_sources.py`:
  - default production source list includes Copernicus.
  - default production source list does not include SOCIB THREDDS model forecasts.
  - setting an experimental flag can include SOCIB later.
- [x] Modify `forecast_sources.py` to gate SOCIB THREDDS behind `PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS=1`.
- [x] Run `pytest test_forecast_sources.py`.

## Task 6: Verification

- [x] Run:
  - `pytest test_ingest_atmosphere.py test_grid_blender.py test_evidence_package.py test_decision_engine.py test_forecast_sources.py`
  - `pytest test_route_analysis.py test_api_app.py`
- [x] Confirm no generated graphics or local artifacts are staged.
- [x] Commit the Phase 1 implementation.

## Out of Scope for Phase 1

- Real Météo-France AROME credentialed download.
- Real AEMET HARMONIE-AROME download.
- Real ECMWF Open Data GRIB download.
- Real Puertos del Estado ingestion.
- Editing root GitHub Actions workflow from this sandbox.

These are deliberately deferred until provider credentials and exact endpoint contracts are confirmed.
