# PredSea System

PredSea is a maritime decision intelligence system for the Balearic Sea. The
current MVP translates ocean forecasts, SOCIB buoy truth, route exposure, vessel
class, and human review into captain-ready operational guidance.

The product direction is deliberately ocean-first. Wind is useful supporting
context when it changes the operational read, but PredSea is not trying to be
another generic wind or weather app.

Core positioning:

```text
Ocean data is everywhere.
Operational decisions are not.
```

## Architecture

- `simulation/`: WRF/WPS Dockerfiles, Fortran namelists, domain setup, and run automation.
- `ingestion/`: GFS/ERA5 data acquisition from cloud object stores.
- `processing/`: NetCDF-to-JSON interpretation using `xarray` and `wrf-python`.
- `vault/`: PostgreSQL/PostGIS schema for forecasts, yacht telemetry, and bias analysis.
- `api/`: FastAPI gateway for the LLM agent.
- `humanintheloop/`: local MVP for captain-facing route decisions, serving
  the live `/routes/{route_id}/briefing` API in WhatsApp/LinkedIn text
  formats.

## Human-in-the-Loop MVP

The current working MVP lives in `humanintheloop/`. It is a lightweight command
line prototype for proving the decision layer before the full owned-modeling
stack exists.

Current operational docs:

- `docs/prediction-etl.md`: ETL, external forecasts, evidence packages, GCS
  output layout, and where new data/model sources should be added.
- `docs/api-whatsapp.md`: deployed API, WhatsApp integration, run selection,
  and future media/map endpoints.

The MVP is a human-in-the-loop intelligence workflow:

```text
forecast + buoy truth + route exposure + vessel class + human review
= captain-ready decision intelligence
```

Current routes in `humanintheloop/routes.json`:

```text
palma_ibiza: Palma -> Ibiza
palma_cabrera: Palma -> Cabrera
ibiza_formentera: Ibiza -> Formentera
alcudia_ciutadella: Alcudia -> Ciutadella
```

Current data sources:

- SOCIB public observations via DataDiscovery.
- Copernicus Marine Mediterranean wave and surface-current forecast subsets.
- SOCIB THREDDS SAPO-IB wave forecasts.
- SOCIB THREDDS WMOP surface-current forecasts.

Current forecast variables:

- `VHM0`: significant wave height.
- `VMDR`: mean wave direction from, used as visual/context information.
- `uo`, `vo`: eastward and northward surface current components.
- `VHM0_SW1`: primary swell significant wave height when provided by the source.

Current observation variables:

- Wave height from SOCIB wave buoys.
- Wave direction from SOCIB wave buoys, visualized as arrows rather than as a
  scalar line chart.
- Water temperature, sea-level pressure, wind speed, and salinity where SOCIB
  exposes them. These are not all validated against forecasts yet because the
  matching forecast variables are not all downloaded in the MVP.

## Human-in-the-Loop Pipeline

1. Data fetch:
   - `socib_public.py` fetches current public SOCIB observations.
   - `fetch_data.py` downloads bounded Copernicus wave/current NetCDF files into
     `humanintheloop/mvp_data/`.
   - `socib_thredds.py` downloads SOCIB THREDDS WMOP/SAPO files and normalizes
     them into the same wave/current variable names.
   - `forecast_sources.py` runs Copernicus and SOCIB independently so one failed
     source does not block the other.

2. Route catalog:
   - `routes.json` defines route IDs, display names, sample points, vessel route
     notes, and validation truth sources.

3. Route forecast sampling:
   - `route_analysis.py` samples each configured route from the forecast grid.
   - Decisions use the exposed-route maximum per hour instead of a broad
     Balearic box average.

4. Vessel-class logic:
   - `small`: under 15m.
   - `medium`: 15-24m.
   - `large`: over 24m.
   - The same forecast can produce different advice depending on vessel class.

5. Briefing generation:
   - `briefing.py` creates route-specific snapshots and text artifacts under
     `mvp_data/routes/<route_id>/`.
   - `briefing_renderers.py` still exposes LinkedIn and WhatsApp-style text
     renderers, but only the live `/routes/{route_id}/briefing` API endpoint
     calls them now. The per-run `briefing.py` pipeline no longer generates
     `briefing_linkedin.txt`/`briefing_whatsapp.txt` files or a WhatsApp-style
     screenshot figure; that generation was removed as unused.

6. Question answering:
   - `decision_engine.py` answers early rule-based captain questions such as:
     - `Can I leave at 17:00?`
     - `Is it safe to stay here?`
     - `What is the best time to leave?`
     - `Can I save fuel?`
   - Answers are now rendered as short captain-facing operational messages,
     not as rigid `Recommendation` / `Reason` templates.

7. Visual output:
   - `map_generator.py` creates first-version Oceanographic Conditions Maps:
     wave-height fields and surface-current vectors, without route overlays.
     This is the lightweight GitHub Actions fallback renderer.
   - `scripts/generate_ocean_conditions_map.py` creates publication maps with
     real Cartopy coastline context, latitude/longitude axes, colorbar, and
     optional current vectors.

8. Validation:
   - `validation_engine.py` compares stored route forecasts against SOCIB truth.
   - Wave-height validation is a scalar time-series comparison and reports MAE.
   - Wave direction is visualized with paired forecast/observed arrows per hour.
   - Direction is not treated as a scalar accuracy plot.
   - Marketing wins are only flagged when a separate baseline forecast exists.

9. Human review:
   - The human reviews the briefing, validation plots, buoy suitability, and
     confidence before publishing or sending advice.
   - The human decides whether the model evidence supports the message.

Current decision behavior:

- Fetches live observations and forecast data.
- Builds route-specific artifacts under `mvp_data/routes/<route_id>/`.
- Samples the selected route corridor instead of using a whole-region Balearic
  average.
- Uses the exposed-route maximum per hour for route decisions.
- Adjusts advice by vessel class: `small`, `medium`, or `large`.
- Answers captain-style questions with:
  - route or location read
  - short evidence explanation
  - vessel-class context when relevant
  - `Confidence`
- Handles specific requested times such as `17:00`.
- Validates stored route forecasts against SOCIB buoy observations with
  `validation_engine.py`, using route-specific truth sources.
- Produces wave-height time-series validation plots and wave-direction vector
  context plots.
- Produces a first-version oceanographic map, currently named
  `route_decision_map.png`, for each daily route artifact folder. The fallback
  map uses the full Balearic forecast region, significant wave height as a color
  field, surface-current vectors, and island labels. Publication maps should be
  generated with `scripts/generate_ocean_conditions_map.py` when real coastline
  detail matters.
- Serves the public website demo through the live API: the demo map loads the
  latest artifact and the demo chat calls `/routes/palma_ibiza/question`.

Next visual priority:

- Improve Oceanographic Conditions Maps with clearer wave scales, current-speed
  legends, and wave direction context.
- Replace the fallback schematic coastline in the automated ETL with the
  Cartopy publication renderer once the GitHub Action runtime is validated.
- Add wave-period/wavelength layers if they become available in the forecast
  download.
- Wind context only when it explains the sea-state decision.

Generate a publication-quality ocean map with real coastline context:

```bash
python scripts/generate_ocean_conditions_map.py \
  --waves humanintheloop/mvp_data/balearic_waves.nc \
  --currents humanintheloop/mvp_data/balearic_currents.nc \
  --time 12:00 \
  --output humanintheloop/artifacts/ocean_conditions_cartopy.png
```

Run from `humanintheloop/`:

```bash
./.venv/bin/python briefing.py \
  --route palma_ibiza \
  --vessel-class medium \
  --question "Can I leave at 17:00?" \
  --location-label "Palma Marina"
```

For a demo conversation time, override the clock:

```bash
./.venv/bin/python briefing.py \
  --route alcudia_ciutadella \
  --vessel-class small \
  --question "Can I leave at 17:00?" \
  --location-label "Palma Marina" \
  --current-time "09:30"
```

Validate stored route forecasts against current SOCIB buoy observations:

```bash
./.venv/bin/python validation_engine.py
```

Validation writes:

```text
mvp_data/validation/<date>/validation_report.json
mvp_data/validation/<date>/marketing_wins.txt
mvp_data/validation/<date>/time_series/time_series_report.json
mvp_data/validation/<date>/time_series/*_wave_timeseries.png
mvp_data/validation/<date>/direction_vectors/direction_vector_report.json
mvp_data/validation/<date>/direction_vectors/*_wave_direction_vectors.png
```

Run MVP tests:

```bash
cd humanintheloop
./.venv/bin/python -m unittest test_socib_scripts.py
```

Important limitation: this is not yet a production chat system. Data refresh is
still coupled to `briefing.py`, unknown routes are not generated automatically,
location sharing is simulated for screenshots, and the question parser is
rule-based. Marketing-win claims require a separate baseline forecast in the
snapshot; the MVP does not claim to beat Copernicus by comparing Copernicus-based
route output against itself. `Alcudia -> Ciutadella` is intentionally marked as
not validated by SOCIB until a suitable Menorca Channel wave source is added.

## Execution Order

1. Phase 1: clear the old prototype and initialize the vertical pipeline layout.
2. Phase 3: build automated GFS ingestion first, so data is available while WRF builds.
3. Phase 2: build the WRF/WPS simulation environment and Balearic domain setup.
4. Phase 4: build the Captain's Intelligence Layer over `wrfout` files.
5. Phase 5: build the Data Assimilation Vault for forecasts, observations, and bias analysis.

## Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

Phase-specific compiled dependencies live beside their modules. For Phase 4,
install the WRF interpreter dependency separately:

```bash
pip install -r processing/requirements.txt
```

## Phase 3 Smoke Test

List the latest GFS keys for the Western Mediterranean without downloading:

```bash
python ingestion/gfs_puller.py --dry-run --max-files 5
```

Download and filter files after installing `wgrib2`:

```bash
conda install -c conda-forge wgrib2
python ingestion/gfs_puller.py --max-files 1
```

## Phase 2 WRF Scaffold

Generate the Balearic 1km nested WPS namelist:

```bash
python simulation/setup_domain.py --output simulation/namelist.wps
```

Build the WRF/WPS image when you are ready for the heavy compile:

```bash
docker build --platform linux/amd64 -t predsea-wrf:4.5 -f simulation/Dockerfile simulation
```

Run `simulation/run_pipeline.sh` inside the image with GFS GRIB2 files mounted at
`/data/gfs`.

## Phase 4 Captain Summary

Run the WRF interpreter against the sample `wrfout_d03` fixture:

```bash
python processing/run_phase4_summary.py
```

The interpreter returns LLM-ready JSON with condition, wind speed, direction,
gust factor, stability, risk assessment, source, location, and supporting
metrics.

Run a route sample across the WRF fixture:

```bash
python processing/run_route_summary.py
```

Run Dijkstra lowest-wind routing across the WRF grid:

```bash
python processing/run_optimal_route.py
```

Compare Dijkstra lowest-wind routing across the 9 km, 3 km, and 1 km sample
domains:

```bash
python processing/run_route_comparison.py
```

Validate forecast distributions against station-style observations:

```bash
python processing/run_observation_validation.py
```

The default observation CSV is a small development fixture. Replace
`ingestion/fixtures/balearic_observations_sample.csv` with SOCIB or Puertos del
Estado observations for real validation.

Compare a GFS-style wind baseline against the PredSea WRF d03 fixture:

```bash
python processing/run_gfs_vs_predsea_validation.py
```

The default GFS NetCDF is the real NOAA GFS 2026-04-29 12Z forecast-hour-006
wind/pressure extraction, valid at the same 2026-04-29 18Z timestamp as the WRF
d03 fixture. Replace the observation CSV with real buoy/station observations for
production validation.
