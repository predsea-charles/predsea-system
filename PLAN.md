# PredSea Modeling Plan

## Human-in-the-Loop MVP Status

Status: working local MVP for route-aware Balearic decision briefings.

This MVP is intentionally simpler than the long-term owned-modeling roadmap
below. Its goal is to prove PredSea's decision value before investing in a full
NEMO/SWAN/LLM/product stack.

Product focus: PredSea should own decision intelligence for the sea. The MVP
should not become another generic weather dashboard. Its outputs should translate
ocean forecasts, SOCIB buoy truth, route exposure, vessel class, and human
review into operational guidance a captain can act on.

Implemented now in `humanintheloop/`:

- SOCIB public observations are fetched and normalized from DataDiscovery.
- Copernicus Marine Mediterranean wave/current forecast subsets are downloaded.
- The decision source no longer uses a broad Balearic box average.
- `humanintheloop/routes.json` configures initial platform routes:
  - `palma_ibiza`
  - `palma_cabrera`
  - `ibiza_formentera`
  - `alcudia_ciutadella`
- The route engine samples the selected route corridor and uses the exposed-route
  maximum per hour (`sampling_method: route_exposed_max`).
- Briefing artifacts are written under `mvp_data/routes/<route_id>/`.
- Vessel class filtering adjusts advice for `small`, `medium`, and `large`
  vessels.
- `validation_engine.py` compares stored route forecasts against SOCIB buoy
  observations and writes validation artifacts. Validation sources are configured
  per route, not globally.
- Wave-height validation uses scalar time-series comparisons and MAE. Wave
  direction is visualized with paired forecast/observed vectors per hour and is
  not treated as a scalar line-chart metric.
- Captain questions can be answered with `briefing.py --question`.
- The decision engine supports these early intents:
  - leave/window timing
  - local stay/move safety
  - conditions at a requested time such as `17:00`
  - first-pass fuel/route-efficiency language
- Answers include `Recommendation`, `Reason`, and `Confidence`.
- The live `/routes/{route_id}/briefing` API endpoint renders WhatsApp- and
  LinkedIn-style text on demand (`briefing_renderers.py`). Per-run static
  WhatsApp/LinkedIn text files and the WhatsApp-style screenshot PNG
  (`chat_figure.py`) were removed as unused; that generation no longer runs.
- Current verification: local `unittest` coverage in
  `humanintheloop/test_socib_scripts.py`.

Current map status:

- `humanintheloop/map_generator.py` creates first-version captain-facing
  Oceanographic Conditions Maps from the existing Copernicus wave/current
  NetCDF files.
- The daily ETL now writes `route_decision_map.png` for each configured route.
- Maps now prioritize full-region oceanographic evidence: significant wave
  height as a color field, surface-current vectors, and island labels. Route
  overlays are intentionally excluded from the map layer.
- `scripts/generate_ocean_conditions_map.py` creates publication maps with real
  Cartopy coastline context and should be used for LinkedIn/web visuals.
- Validation plots still exist as diagnostic artifacts, separate from
  captain-facing route maps.
- The current maps are intentionally lightweight Pillow renders, not final
  Cartopy-grade cartographic products.

Current MVP command examples:

```bash
cd humanintheloop

# Use real current local time
./.venv/bin/python briefing.py \
  --route palma_ibiza \
  --vessel-class medium \
  --question "Can I leave at 17:00?" \
  --location-label "Palma Marina"

# Force a demo time
./.venv/bin/python briefing.py \
  --route alcudia_ciutadella \
  --vessel-class small \
  --question "Can I leave at 17:00?" \
  --location-label "Palma Marina" \
  --current-time "09:30"

./.venv/bin/python validation_engine.py
```

Known MVP limitations:

- Routes use a small fixed set of representative points rather than an automatic
  generated corridor width.
- The question parser is rule-based, not yet LLM-backed.
- Location sharing is simulated for screenshots; no real WhatsApp/GPS
  integration exists yet.
- Validation can compare PredSea route forecasts against observed SOCIB buoy
  truth. `Palma -> Ibiza` and `Ibiza -> Formentera` use Canal de Ibiza;
  `Palma -> Cabrera` uses Bahia de Palma; `Alcudia -> Ciutadella` is marked as
  having no suitable SOCIB wave buoy yet. It only flags a `Marketing Win` when a
  separate baseline forecast is present in the snapshot; the system does not
  claim to beat Copernicus by comparing Copernicus-derived output against itself.
- The system still refreshes data during each `briefing.py` run; production
  should separate scheduled data refresh from on-demand question answering.
- SOCIB WMOP/SAPO are not yet integrated; Copernicus is the working forecast
  source for the MVP.

Next MVP milestones:

1. Improve Oceanographic Conditions Maps with cleaner geography, better variable
   scales, wave direction context, and clearer current-speed legends.
2. Generate one Balearic Overview Conditions Map for LinkedIn and daily review.
3. Use wind only as supporting context when it changes the operational read
   (for example wind against current, wind aligned with swell, or afternoon sea
   breeze affecting comfort). The product remains ocean-first.
4. Add morning and afternoon/evening briefing modes so maps and text do not
   recycle stale "before midday" language after the day has moved on.
5. Replace fixed route points with generated route corridor sampling.
6. Add arbitrary port/marina lookup for routes not yet in `routes.json`.
7. Split the pipeline into:
   - scheduled data refresh
   - on-demand question answering from cached snapshots
8. Add query-context extraction:
   - current/shared location
   - destination
   - requested time
   - decision intent
9. Add an LLM communication layer that interprets structured facts but does not
   invent forecasts.
10. Add more decision types: stay/move, leave/wait, comfort/risk, fuel/reroute.
11. Add SOCIB WMOP/SAPO where they improve local current/wave decisions.
12. Store explicit baseline forecasts for fair PredSea-vs-global-app validation.
13. Add a reliable Menorca Channel truth source for Alcudia-Ciutadella validation.
14. Add scalar forecast variables for water temperature and wind speed so they
    can be validated against SOCIB observations.

## Phase 1: Atmospheric Foundation

Goal: own the high-resolution atmospheric forcing pipeline for the Balearic Sea.

Status: mostly complete for the prototype.

- Repository structure created: `simulation/`, `ingestion/`, `processing/`, `vault/`, `api/`.
- WRF/WPS Docker scaffold created and successfully built on x86_64.
- Balearic WPS domain generator created.
- GFS latest-cycle ingestion from NOAA public S3 implemented.
- WRF `wrfout` interpretation implemented for d01/d02/d03 fixtures.
- Route sampling and forecast-vs-observation distribution scoring implemented.

Important note: Dijkstra over wind-only fields is useful as a graph-routing proof,
but it is not the right marine-routing foundation. Marine routing should be based
on waves, currents, vessel heading, and sea-state comfort/risk.

## Phase 2: Owned Oceanographic Modeling

Goal: add proprietary ocean conditions using NEMO for currents/sea state context
and SWAN for coastal waves.

Selected first domain:

```text
lon: 1.0 to 5.0
lat: 38.0 to 41.0
focus: Mallorca, Menorca Channel, Ibiza Channel, Balearic inter-island routes
```

The domain should match the WRF nested Balearic coverage as closely as practical.

Selected first forecast target:

```text
forecast horizon: 24 hours
output interval: hourly
```

Selected model pair:

- NEMO: currents, sea level, temperature, salinity.
- SWAN: coastal and channel-scale waves.

Why SWAN: PredSea is focused on yacht operations around islands, channels, and
coastal waters. SWAN is the better first wave model for shallow/coastal
transformation, local wind-wave growth, bathymetric effects, and island sheltering.

## Phase 2A: NEMO Minimal Viable Run

User tasks:

- Decide where NEMO will run. Recommendation: use the Google Cloud x86_64 VM,
  not the local Mac, for full model builds and production-style runs.
- Install the Copernicus Marine Toolbox on the run machine.
- Confirm access to Copernicus Marine Data Store credentials with
  `copernicusmarine login --check-credentials-valid`.
- Download Mediterranean physical analysis/forecast data for initial and boundary
  conditions.
- Prepare bathymetry for the Balearic domain.
- Prepare or generate the NEMO grid, vertical levels, masks, and coordinates.
- Feed atmospheric forcing from WRF when available; use GFS forcing for early
  smoke tests if needed.
- Run a 24h hourly-output test.

Expected first NEMO output variables:

```text
sea_surface_height
sea_surface_temperature
u_current
v_current
salinity
```

Repo tasks:

- Create `simulation/nemo/`.
- Add NEMO build/run documentation.
- Add configuration placeholders for Balearic domain bounds and hourly output.
- Add `processing/nemo_interpreter.py`.
- Add synthetic NEMO NetCDF fixture for tests.
- Add route sampling over NEMO currents.

## Phase 2B: SWAN Minimal Viable Run

User tasks:

- Build/install SWAN on the same x86_64 VM.
- Prepare SWAN computational grid for the same Balearic bounds.
- Prepare bathymetry for SWAN.
- Use WRF 10m wind as preferred forcing; GFS wind is acceptable for smoke tests.
- Use Copernicus Marine wave products, global WAVEWATCH III, or another basin
  wave source as open boundary conditions for the first test.
- Run a 24h hourly-output test.

Expected first SWAN output variables:

```text
significant_wave_height
peak_wave_period
mean_wave_direction
```

Repo tasks:

- Create `simulation/swan/`.
- Add SWAN build/run documentation.
- Add `processing/swan_interpreter.py`.
- Add synthetic SWAN NetCDF fixture for tests.
- Add route sampling over wave height, period, and direction.

## Phase 2C: Marine Fusion Layer

Goal: combine WRF + NEMO + SWAN into captain-ready marine intelligence.

Create:

```text
processing/marine_fusion.py
```

Input:

- WRF wind and pressure.
- NEMO currents, sea surface height, sea surface temperature.
- SWAN wave height, period, direction.
- Vessel route and nominal cruise speed.

Output:

```json
{
  "comfort_status": "comfortable | moderate | rough | high_risk",
  "fuel_penalty": 1.18,
  "eta_impact_minutes": 24,
  "worst_segment": {},
  "captain_summary": ""
}
```

Minimal comfort thresholds:

```text
comfortable: waves < 0.8m and currents < 0.5 kt
moderate:    waves 0.8-1.5m or currents 0.5-1.2 kt
rough:       waves 1.5-2.2m or currents 1.2-2.0 kt
high_risk:   waves > 2.2m or currents > 2.0 kt
```

Minimal fuel logic:

```text
fuel_penalty = distance_penalty + opposing_current_penalty + wave_resistance_penalty
```

Dijkstra should return only after this fusion layer exists. The graph cost should
use waves and opposing currents, not wind alone.

## Phase 2D: Validation

Goal: prove which resolution/model configuration is closest to reality.

Validation sources:

- Buoy wave observations.
- In-situ current observations where available.
- Sea temperature observations.
- Yacht telemetry later.

Metrics:

```text
bias
MAE
RMSE
distribution similarity
station distance from nearest grid cell
```

Existing repo support:

- `ingestion/observations_client.py` normalizes station-style CSV observations.
- `processing/forecast_validation.py` compares forecast and observation
  distributions.

Next extension:

- Add validation for NEMO currents.
- Add validation for SWAN wave height and period.
- Store validated forecasts and observations in the future PostGIS vault.

## Local Machine vs Cloud

Local machine is useful for:

- Editing configs.
- Running Python interpreters.
- Testing synthetic fixtures.
- Inspecting small NetCDF outputs.
- Running tiny toy NEMO/SWAN cases only if dependencies compile cleanly.

Cloud x86_64 VM is recommended for:

- Building NEMO, XIOS, and SWAN.
- Running 24h Balearic simulations.
- Running repeated forecast cycles.
- Keeping the pipeline close to production.

Reason: NEMO/XIOS/SWAN builds are compiler/MPI/NetCDF-heavy. The local Mac,
especially Apple Silicon, can work for development but is not the lowest-friction
place for repeatable operational model runs.

## Immediate Next Tasks

User:

1. Confirm Copernicus Marine credentials, not only EUMETSAT credentials.
2. Install `copernicusmarine` on the VM.
3. Run `copernicusmarine login`.
4. Confirm credentials with `copernicusmarine login --check-credentials-valid`.
5. Keep first domain as `lon 1.0..5.0`, `lat 38.0..41.0`.
6. Keep first target as `24h`, hourly output.

Repo:

1. Create `simulation/nemo/` and `simulation/swan/` scaffolds.
2. Add synthetic NEMO and SWAN fixtures.
3. Implement `nemo_interpreter.py`.
4. Implement `swan_interpreter.py`.
5. Implement `marine_fusion.py`.
6. Add tests and runners for the minimal marine summary.
