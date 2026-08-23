# PredSea Prediction and ETL

This document describes the current PredSea prediction pipeline: what it
fetches, what it produces, where outputs are stored, and where future data
sources should be added.

## Current Purpose

The ETL does not answer captain questions directly. Its job is to build a
decision-ready evidence package from external forecasts, SOCIB observations,
route geometry, vessel class, and operational interpretation.

```text
external forecasts + SOCIB observations + route sampling
        -> evidence package
        -> API / WhatsApp decision layer
```

The API should be able to answer many questions from the latest evidence
without downloading forecast data during the request.

## Current Availability Snapshot

This is the practical inventory of what PredSea has available today.

| Layer | Production status | Source | Resolution | Time step | Used for |
| --- | --- | --- | --- | --- | --- |
| Waves | Default | Copernicus Marine Mediterranean wave forecast | about 4.2 km | hourly | route decisions, maps, route-relative sea state |
| Currents | Default | Copernicus Marine Mediterranean surface currents | about 4.2 km | hourly | current speed maps, route context, location screening |
| Observations | Opportunistic | SOCIB public buoy/platform observations | point stations | latest available sample | ground-truth check when fresh |
| SOCIB model waves | Experimental opt-in | SOCIB THREDDS SAPO-IB | provider native grid | provider dependent | parallel evidence package when enabled |
| SOCIB model currents | Experimental opt-in | SOCIB THREDDS WMOP | provider native grid | provider dependent | parallel evidence package when enabled |
| Atmospheric wind | Optional opt-in | Météo-France AROME, AEMET HARMONIE-AROME, ECMWF fallback | 1.3 km, 2.5 km, fallback tier | provider dependent | wind lineage and future wind-aware decisions |

Default production runs currently rely on Copernicus for forecast fields and
SOCIB only for observations when fresh observations are available. SOCIB model
forecasts and atmospheric ingestion are available behind feature flags because
provider availability and credentials vary.

## Available Forecast Variables

These are the normalized variables the ETL can currently expose to evidence,
maps, or API responses.

| PredSea variable | Source/model variable | Units | Route evidence | Regional map/API overlay | Notes |
| --- | --- | --- | --- | --- | --- |
| `wave_height` | `VHM0` | m | yes | yes | Significant wave height; main sea-state field. |
| `wave_direction` | `VMDR` | degrees, from | yes | no | Used for route-relative sea-state interpretation. |
| `swell_1_height` | `VHM0_SW1` | m | yes | yes | Primary swell height when provided by source. |
| `swell_1_direction` | `VMDR_SW1` | degrees, from | yes | yes | Primary swell direction when provided by source. |
| `swell_2_height` | `VHM0_SW2` | m | yes | yes | Secondary swell height when provided by source. |
| `swell_2_direction` | `VMDR_SW2` | degrees, from | yes | yes | Secondary swell direction when provided by source. |
| `wind_wave_height` | `VHM0_WW` | m | yes | yes | Wind-wave component height when provided by source. |
| `wind_wave_direction` | `VMDR_WW` | degrees, from | yes | yes | Wind-wave component direction when provided by source. |
| `current_speed` | derived from `uo`, `vo` | m/s on maps, kn in route summaries | yes | yes | Surface current speed. |
| `current_direction` | derived from `uo`, `vo` | degrees | partial | no | Used mostly as vector/context evidence. |
| `wind_speed` | atmospheric provider dependent | m/s or kt after normalization | lineage only today | no | Optional layer; not yet a default decision driver. |
| `wind_direction` | atmospheric provider dependent | degrees | lineage only today | no | Optional layer; not yet a default decision driver. |

Important current gaps:

- wave period is not yet part of the production evidence package
- wind gusts are not yet part of the default evidence package
- bathymetry, seabed type, anchoring restrictions, marina constraints, and
  legal exclusion zones are not included
- alternate route optimization is not implemented yet
- model-delta alerts and numeric confidence scores are planned but not exposed
  as stable API fields yet

## Current Data Sources

Current external sources:

- Copernicus Marine Mediterranean wave forecast.
- Copernicus Marine Mediterranean surface-current forecast.
- SOCIB THREDDS SAPO-IB wave forecast, opt-in only with
  `PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS=1`.
- SOCIB THREDDS WMOP surface-current forecast, opt-in only with
  `PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS=1`.
- SOCIB public observations via DataDiscovery.
- Optional atmospheric wind evidence:
  - Météo-France AROME, 1.3 km, when `METEO_FRANCE_API_KEY` is configured and
    `PREDSEA_ENABLE_ATMOSPHERIC_INGESTION=1`.
  - AEMET HARMONIE-AROME, 2.5 km, when `AEMET_API_KEY` is configured and
    `PREDSEA_ENABLE_ATMOSPHERIC_INGESTION=1`.
  - ECMWF Open Data fallback when atmospheric ingestion is enabled.

Current forecast variables are normalized into the PredSea names listed in
`Available Forecast Variables` above. The underlying model variables include
wave height/direction, swell partitions, wind-wave partitions, and surface
current vector components when the provider exposes them.

The current Copernicus routing box (`humanintheloop/fetch_data.py`) is
intentionally wider than the original Balearic-only setup so PredSea can cover
mainland transit lanes to Barcelona and Valencia, plus every region defined in
`simulation/marine/regions/*.json`, in the same evidence pipeline. The
operating box now spans:

- latitude 35.0 to 44.5
- longitude -6.0 to 16.5

That range covers the Alboran Sea west of Gibraltar, the Balearics, the Gulf
of Lion, mainland Spain and France, Sardinia/Corsica, and the Tyrrhenian and
Algerian basins. `lon_min` was extended from -1.0 to -6.0 after confirming the
narrower box did not reach the Alboran region's bounding box
(`alboran_1km.json`'s `longitude_min` is -6.0), which would have produced
empty forecast data for any Alboran-area route.

Interpretation is allowed to read coordinate vectors anywhere in that corridor,
including mainland-to-islands crossings and inter-island routes, but it should
still speak in route-relative and vessel-relative terms rather than raw grid
cells.

The single `regional_evidence.json` written per run also uses a basin-wide
`region_id` (`western_mediterranean`) rather than a narrower sub-region name,
since one run's Copernicus/WRF forcing and maps already cover the whole basin
for every route in `routes.json`, not one specific sub-region.

The atmospheric wind layer uses the same expanded mainland corridor, so AROME,
AEMET HARMONIE-AROME, and ECMWF all cover the same broader decision area when
their credentials or open data availability allow it.

Copernicus is the default production forecast source. SOCIB model forecasts are
kept as an experimental/secondary source because provider monitoring showed
SOCIB THREDDS can be slow or unavailable from GitHub Actions. When SOCIB model
forecasts are enabled and available, they are generated as parallel evidence
packages. Copernicus remains the preferred source for the legacy top-level route
artifacts unless it is unavailable. SOCIB output is normalized to the same
variable names and units so `route_analysis.py`, map generation, and the API can
remain source-agnostic.

Atmospheric wind is now represented as a source-aware evidence layer. It is not
yet required for the production ETL. When enabled, the ETL records wind lineage
inside every route evidence package so the Co-Captain can say whether wind
context came from high-resolution local models or a global fallback.

Current observation variables depend on each SOCIB platform. When available,
they can include:

- wave height
- wave direction
- water temperature
- salinity
- sea-level pressure
- air pressure

SOCIB observations older than the freshness threshold are filtered out before
they enter the evidence package.

## Data Source Responsibilities

PredSea separates three concerns:

```text
data providers -> normalized evidence -> captain intelligence
```

The ETL is responsible for:

- fetching external model and observation data
- normalizing variables into common names and units
- sampling routes, points, or regions
- recording model metadata such as source, run time, resolution, and freshness
- writing the evidence package to local outputs and GCS

The API is responsible for:

- selecting the right stored evidence package
- answering captain questions from that evidence
- answering Phase 1 free-location questions by sampling map grids around a
  shared GPS point
- returning text and media URLs

Captain knowledge is responsible for:

- interpreting risk, comfort, and operational trade-offs
- adapting the same data to vessel class, route exposure, timing, and local
  experience

Do not make the API download new model files during a captain request. If a
question needs more data than the ETL prepared, add that data to the evidence
package first.

## Phase 1 Location Intelligence

The API supports `POST /question` for questions such as:

```text
I am at this position, where should I anchor tonight?
Can I stay here?
```

The request must include latitude and longitude. The API samples the nearest
forecast map grids generated by the ETL, currently wave height, current speed,
and swell height when available. This is a screening layer, not a final
anchoring clearance.

Known Phase 1 limitations:

- no seabed type
- no depth or bathymetry
- no legal anchoring restrictions
- no local shelter geometry
- no nearby anchorage search

The answer must clearly state these limitations and use conservative language.

Each run now writes a run-level regional evidence contract:

```text
outputs/<date>/runs/<run_id>/regional_evidence.json
```

This file is created from the generated map overlay indexes and records:

- supported API modes: `route_question`, `location_question`, `map_inspect`
- available variables, units, time coverage, bounds, color scale, and index path
- route IDs included in the run
- forecast sources available for the run
- Phase 1 limitations for location questions

`run_manifest.json` and `latest_run.json` include a compact
`regional_evidence` pointer so the API and WhatsApp layer can detect whether
free-location questions are supported by the current run.

## Current Routes

Routes are configured in:

```text
humanintheloop/routes.json
```

Current routes:

- `palma_ibiza`
- `palma_cabrera`
- `ibiza_formentera`
- `alcudia_ciutadella`

Each route defines:

- origin
- destination
- sample points
- operational route note
- wave validation truth source, when available
- current validation truth source, when available

Route decisions use the exposed route maximum per hour, not a broad Balearic
box average.
box average.

## Run Frequency

GitHub Actions currently runs the ETL three times per day:

- 08:30 Mallorca summer time
- 13:30 Mallorca summer time
- 17:30 Mallorca summer time

The workflow is:

```text
.github/workflows/predsea-daily.yml
```

GitHub cron runs in UTC, so the schedule may need seasonal adjustment if the
operational promise becomes exact local time all year.

## Production Orchestrator

The production ETL entrypoint is:

```text
scripts/generate_daily_briefing.py
```

This script remains the scheduled GitHub Actions path because it already owns:

- route artifact generation
- source-specific output folders
- preferred-source copying
- Leaflet overlay generation
- `regional_evidence.json`
- run manifests
- GCS-ready output layout

`humanintheloop/pipeline.py` remains useful as a reference/orchestration layer
for the multi-tier architecture, but the production strategy is to evolve
`generate_daily_briefing.py` gradually rather than replacing it.

Current production-safe multi-tier behavior:

- Copernicus forecast source runs by default.
- SOCIB model forecasts run only when `PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS=1`.
- Atmospheric wind ingestion runs only when
  `PREDSEA_ENABLE_ATMOSPHERIC_INGESTION=1`.
- If atmospheric ingestion is disabled, route evidence records
  `data_lineage.wind_forecast.status = "not_configured"`.
- If atmospheric ingestion is enabled but fails, route evidence records
  `data_lineage.wind_forecast.status = "error"` and the ETL continues.
- SOCIB observations continue to populate the ground-truth lineage when
  available.

Every route snapshot now includes:

```json
{
  "data_lineage": {
    "wind_forecast": {
      "source": null,
      "resolution_km": null,
      "status": "not_configured",
      "tier": null
    },
    "ocean_forecast": {
      "source": "copernicus_med",
      "resolution_km": 4.0,
      "status": "active"
    },
    "ground_truth_validation": {
      "source": "socib_observations",
      "status": "matched_successfully",
      "station_count": 3
    }
  }
}
```

## Output Layout

The ETL now writes run-based outputs.

```text
outputs/
  YYYY-MM-DD/
    latest_run.json
    runs/
      RUN_ID/
        run_manifest.json
        regional_evidence.json
        validation/
          observation_samples.jsonl
          forecast_index.jsonl
          matched_validation.jsonl
          validation_summary.json
        maps/
          wave_height/
            index.json
            wave_height_YYYYMMDD_HHMMSSZ.png
            wave_height_YYYYMMDD_HHMMSSZ.grid.json
          current_speed/
            index.json
            current_speed_YYYYMMDD_HHMMSSZ.png
            current_speed_YYYYMMDD_HHMMSSZ.grid.json
        palma_ibiza/
          evidence.json
          daily_snapshot.json
          route_decision_map.png
```

Example run ID:

```text
2026-05-31T0058Z
```

The same structure is uploaded to Google Cloud Storage:

```text
gs://predsea-daily-outputs/predictions/YYYY-MM-DD/
```

The API reads GCS first and local bundled predictions only as fallback.

## Main Artifacts

`evidence.json`

The forward-compatible decision package. It contains:

- route subject
- forecast variables
- SOCIB observations
- operational interpretation
- data-quality notes
- `decision_context` for current `/briefing` and `/question` behavior

`daily_snapshot.json`

Legacy-compatible route snapshot. Still used as fallback and for some existing
renderers.

WhatsApp- and LinkedIn-style text used to be pre-generated per run as
`briefing_whatsapp.txt`/`briefing_linkedin.txt`, with a matching
`predsea_whatsapp_figure.png` chat-style screenshot. That per-run generation
was removed as unused; the live `/routes/{route_id}/briefing?format=whatsapp|linkedin`
API endpoint now renders the same text on demand from `briefing_renderers.py`.

`route_decision_map.png`

Current oceanographic map artifact. Despite the name, the product direction is
to show physical sea conditions, not only route advice.

`maps/<variable>/index.json`

Regional map catalog for one variable. The API uses it to select the closest
overlay to a requested time and return a Leaflet-compatible image overlay.

`maps/<variable>/<variable>_*.png`

Transparent or semi-transparent PNG overlay for the selected regional forecast
field.

`maps/<variable>/<variable>_*.grid.json`

Sampleable grid used by `GET /maps/inspect` and by Phase 1 location questions.

`regional_evidence.json`

Run-level contract that tells the API which variables, modes, bounds, and
limitations are officially supported by this run.

`validation/observation_samples.jsonl`

Long-format archive of the latest observation samples fetched by the ETL run.
Each row records provider, station, observation timestamp, variable, value,
units, raw value, and collection time. This is the start of the long-term
forecast-vs-reality database.

`validation/forecast_index.jsonl`

Long-format forecast target index. Each row records route, forecast run ID,
forecast creation timestamp, target forecast timestamp, variable, forecast
value, units, source, resolution, truth station, and lead time.

`validation/matched_validation.jsonl`

Rows where an observation sample can be linked to a forecast target by station,
variable, and timestamp. These rows include forecast value, observed value,
error, absolute error, lead time, model source, and resolution.

`validation/validation_summary.json`

Run-level validation summary with row counts and simple metrics such as MAE and
bias by variable when matches are available.

## How To Run Locally

From the repo root:

```bash
python scripts/generate_daily_briefing.py
```

Run one route:

```bash
python scripts/generate_daily_briefing.py \
  --route palma_ibiza
```

Run one route with a fixed date and run ID:

```bash
python scripts/generate_daily_briefing.py \
  --date 2026-05-31 \
  --run-id 2026-05-31T1230Z \
  --route palma_ibiza
```

Skip maps for a fast smoke test:

```bash
python scripts/generate_daily_briefing.py \
  --output-root /tmp/predsea-smoke \
  --date 2026-05-31 \
  --run-id 2026-05-31T1230Z \
  --route palma_ibiza \
  --skip-maps
```

Export a web-demo bundle from the latest run:

```bash
python scripts/export_web_demo_bundle.py \
  --input-root outputs \
  --output-dir outputs/web-demo \
  --featured-route palma_ibiza
```

## Cloud Upload

GitHub Actions authenticates with:

```text
GCP_SA_KEY
```

and syncs the latest dated output folder to:

```text
gs://predsea-daily-outputs/predictions/YYYY-MM-DD
```

Manual upload:

```bash
gcloud storage rsync --recursive \
  outputs/2026-05-31 \
  gs://predsea-daily-outputs/predictions/2026-05-31
```

## Where To Add More External Models

New external forecast sources should be added to the ETL/data layer, not the
API.

Recommended future structure:

```text
humanintheloop/providers/
  copernicus.py
  socib_thredds.py
  ecmwf.py
  noaa_gfs.py

humanintheloop/normalizers/
  waves.py
  currents.py
  wind.py

humanintheloop/samplers/
  route_sampling.py
  point_sampling.py
  region_sampling.py
```

Each provider should normalize into common variables before evidence packaging:

- wave height
- wave direction
- wave period
- current speed
- current direction
- wind speed
- wind direction
- water temperature
- model run time
- grid resolution
- coverage area
- source freshness

The API should not need to know whether the source was Copernicus, SOCIB
WMOP/SAPO, ECMWF, or a future PredSea internal model.

## Parallel Forecast Packages

Each ETL run writes source-specific evidence packages:

```text
outputs/<date>/runs/<run_id>/sources/copernicus/<route_id>/
outputs/<date>/runs/<run_id>/sources/socib/<route_id>/
```

The preferred source is also copied to the legacy route location:

```text
outputs/<date>/runs/<run_id>/<route_id>/
```

The preferred source also drives the run-level map overlays and regional
evidence package:

```text
outputs/<date>/runs/<run_id>/maps/<variable>/index.json
outputs/<date>/runs/<run_id>/regional_evidence.json
```

This keeps the current API and WhatsApp integration stable while making model
comparison possible. `run_manifest.json` records each source with:

- `id`
- `label`
- `available`
- `preferred`
- `error`, when a source failed
- `metadata`, when a source provides model URLs or names

Source responsibilities:

- `humanintheloop/fetch_data.py` downloads Copernicus NetCDF subsets.
- `humanintheloop/socib_thredds.py` downloads and normalizes SOCIB THREDDS
  WMOP/SAPO files when the experimental SOCIB model forecast flag is enabled.
- `humanintheloop/forecast_sources.py` runs all configured sources
  independently and marks the preferred source.
- `humanintheloop/fetch_forecast_source.py` fetches one source in a bounded
  subprocess so a slow external provider cannot hang the whole ETL.
- `humanintheloop/ingest_atmosphere.py` selects the best available atmospheric
  wind source from AROME, AEMET HARMONIE-AROME, and ECMWF when atmospheric
  ingestion is enabled.
- `humanintheloop/fetch_meteo_france.py`, `humanintheloop/fetch_aemet.py`, and
  `humanintheloop/fetch_ecmwf.py` are the current atmospheric fetcher modules.
- `humanintheloop/grid_blender.py` can interpolate coarser ocean fields onto the
  active wind grid for future blended products.
- `scripts/generate_daily_briefing.py` builds route artifacts for every
  available source and attaches `data_lineage` to each route snapshot.

`PREDSEA_SOURCE_TIMEOUT_SECONDS` controls the per-source timeout. GitHub
Actions currently sets it to `900` seconds. If one source times out, the ETL
records that source as unavailable in `run_manifest.json` and continues with
any other available source.

Important feature flags:

- `PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS=1`: include SOCIB THREDDS model
  forecasts as a parallel forecast package.
- `PREDSEA_ENABLE_ATMOSPHERIC_INGESTION=1`: include atmospheric wind lineage in
  route evidence. This requires the atmospheric fetcher dependencies and, for
  AROME/AEMET, provider API keys.
- `METEO_FRANCE_API_KEY`: enables Météo-France AROME as tier 1 wind source.
- `AEMET_API_KEY`: enables AEMET HARMONIE-AROME as tier 2 wind source.

## Where To Add More Variables

Add new variables in this order:

1. Fetch or expose the variable in the relevant provider/download script.
2. Normalize it into common units and names.
3. Sample it along routes, points, or regions.
4. Add it to `evidence.json` with source metadata and freshness.
5. Decide whether it should affect `decision_context`.
6. Update API and renderer tests only if the variable changes captain-facing
   behavior.

Practical examples:

- Wave period or wavelength should be added to the wave provider/normalizer,
  then route sampled alongside `VHM0`.
- Wind should be added as supporting context only when it explains the sea-state
  decision. PredSea should stay ocean-first.
- Water temperature is useful for observations and comfort context, but should
  not normally drive go/no-go routing advice.
- Current direction should usually be visual/vector evidence, not scalar text
  unless it changes fuel, drift, or crossing comfort.

Likely files to touch today:

```text
humanintheloop/fetch_data.py
humanintheloop/forecast_sources.py
humanintheloop/socib_thredds.py
humanintheloop/socib_public.py
humanintheloop/route_analysis.py
humanintheloop/evidence_packager.py
humanintheloop/map_generator.py
scripts/generate_leaflet_overlays.py
scripts/generate_daily_briefing.py
humanintheloop/test_socib_scripts.py
humanintheloop/test_api_app.py
```

If a variable only appears on maps, add it to the map/overlay scripts and media
metadata. If it changes advice, also update `decision_engine.py` and tests.

If a variable should be validated over time, also add it to
`humanintheloop/validation_archive.py`:

- `OBSERVATION_VARIABLES` for observed station fields
- `FORECAST_VARIABLES` for forecast target fields
- unit normalization if the provider returns strings such as compass
  directions

The validation archive is intentionally long-format so it can grow from waves
and currents into weather fields such as temperature, rainfall, wind speed,
wind direction, and gusts.

## Forecast vs Reality Validation Archive

Every production ETL run now writes a validation archive:

```text
outputs/<date>/runs/<run_id>/validation/
  observation_samples.jsonl
  forecast_index.jsonl
  matched_validation.jsonl
  validation_summary.json
```

This is the first implementation of the Graham-style validation database.

What it can answer now:

- Which route forecast matched the available SOCIB buoy wave height?
- What was the forecast error for a station/time/variable?
- What was the model source and resolution for the forecast?
- What was the lead time between the ETL forecast timestamp and the target
  observation timestamp?

Current validation variables:

- observed SOCIB wave height
- observed SOCIB wave direction when available
- water temperature, salinity, sea-level pressure, and air pressure as
  observation archive fields
- forecast wave height and direction
- forecast current speed and direction
- forecast swell 1, swell 2, and wind-wave height/direction

Current limitations:

- the archive stores the latest observation samples fetched by each ETL run,
  not a complete provider backfill
- matched validation only works when station, variable, and timestamp align
- wave/current validation depends on route-level truth station configuration in
  `routes.json`
- weather validation for rainfall, air temperature, wind, and gusts needs AEMET,
  ECMWF, or other weather-station ingestion added first
- forecast rows with negative lead time are archived for traceability but
  excluded from matched validation metrics

This gives PredSea the structure needed to build a 6-12 month accuracy database:

```text
forecast run -> target time -> location/station -> actual observation -> error
```

Future work should add:

- AEMET weather station observations
- ECMWF/AEMET/AROME weather forecast fields
- rainfall, air temperature, wind speed, wind direction, and gust validation
- seasonal dashboards with MAE, RMSE, bias, and event-specific diagnostics

### Backfill Validation Archives From GCS

Historical run-based ETL outputs can be backfilled directly in Google Cloud
Storage with:

```bash
python scripts/backfill_validation_archive.py \
  --bucket predsea-daily-outputs \
  --prefix predictions \
  --auth gcloud
```

By default this is a dry-run. To write the validation files:

```bash
python scripts/backfill_validation_archive.py \
  --bucket predsea-daily-outputs \
  --prefix predictions \
  --auth gcloud \
  --apply
```

Useful options:

- `--date-from YYYY-MM-DD`
- `--date-to YYYY-MM-DD`
- `--run-id 2026-06-09T1623Z`
- `--limit 5`
- `--overwrite`

On Charles' local machine, `--auth gcloud` is preferred because the active
`gcloud` account is `hello@predsea.com`, while local Application Default
Credentials may point to another Google account.

## Where To Add Graham's Captain Knowledge

Captain knowledge should not live in the ETL. It belongs in the decision layer
above the normalized evidence.

Current structure:

```text
humanintheloop/captain_knowledge/
  graham_cases.json
  graham_rules.yaml
  vessel_thresholds.yaml
  route_exposure_notes.yaml
humanintheloop/captain_knowledge.py
```

The ETL produces evidence. Graham's knowledge interprets evidence.

Rule format:

```json
{
  "id": "menorca_channel_northerly_more_exposed",
  "source": "graham",
  "condition": {
    "route_ids": ["alcudia_ciutadella"],
    "direction_sector": "N",
    "min_wave_m": 1.2
  },
  "operational_consequence": "The Menorca Channel deserves a more conservative read with northerly sea states than the same height on more protected routes.",
  "preferred_action": "Prefer early conservative timing or wait for the easing period, especially for smaller vessels.",
  "confidence": "high"
}
```

Good Graham knowledge is specific:

- route or region
- vessel class
- sea/wind/current pattern
- time-of-day or exposure nuance
- operational consequence
- preferred action
- confidence or source note

Avoid storing vague comments such as "be careful in rough seas." Those should
be rewritten into testable operational rules or saved as interview notes until
they can be made specific.

When Graham gives stories outside the Balearics, keep them. Store them with a
different `region` and mark them as transferable only if the underlying pattern
is general, for example current-against-wind, lee shore, harbor entrance surge,
or vessel-size sensitivity. Do not apply non-Balearic local rules blindly to
Balearic routes.

Future files likely to change:

```text
humanintheloop/captain_knowledge/graham_rules.yaml
humanintheloop/captain_knowledge/graham_cases.json
humanintheloop/captain_knowledge/vessel_thresholds.yaml
humanintheloop/captain_knowledge/route_exposure_notes.yaml
humanintheloop/captain_knowledge.py
humanintheloop/decision_engine.py
humanintheloop/test_captain_knowledge.py
humanintheloop/test_decision_engine.py
```

Graham's reviewed rules now feed the interpretation layer before the final
answer is rendered:

```text
evidence package
        -> operational rule matching
        -> route/vessel/timing interpretation
        -> captain-facing answer
```

Route evidence also includes operational segments:

```json
{
  "route_segments": {
    "departure_conditions": {},
    "open_water_conditions": {},
    "arrival_conditions": {},
    "worst_segment": {},
    "best_departure_window": {}
  }
}
```

This lets PredSea say, for example, "Worst conditions are expected in the
open-water section around 14:00" instead of only reporting the route maximum.

## Where Internal Dynamical Models Would Fit Later

Running WRF, ROMS, SWAN, or WaveWatch III is a separate numerical modeling
layer. It should not be embedded in the API or the lightweight ETL.

Future structure:

```text
modeling/
  wrf/
  roms/
  waves/
  coupling/
  postprocess/
```

Those model outputs should still be converted into the same evidence package
format. This keeps the WhatsApp/API layer stable whether forecasts come from
Copernicus, SOCIB, or PredSea's own model.

## Next Useful Additions

- Add explicit comparison artifacts: Copernicus vs SOCIB vs buoy truth.
- Add richer model metadata to `evidence.json`: model run time, resolution,
  forecast horizon, source URL, and native variable names.
- Add point and region evidence packages for questions such as "Is it safe to
  stay here?" or "Where can I anchor near Formentera?"
- Add signed GCS media URLs for maps and WhatsApp images.
- Add data-quality warnings when observations are stale or model files are old.
