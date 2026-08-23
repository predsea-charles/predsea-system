# PredSea Observation Layer

This document explains how PredSea collects, normalizes, stores, and exposes
marine observations.

The short version:

- PredSea ingests observations from **Puertos del Estado** and **EMODnet Physics**
  as first-class observation sources.
- **Portus observations** can be kept as an additional layer.
- **SOCIB is not part of the active observation ETL path because all SOCIB instruments are also part of Puertos del Estado**.
- Forecasts are handled separately from observations.
- The canonical output is a normalized observation archive and a BigQuery table.

## What the observation layer is for

The observation layer provides the live and recent marine measurements that
PredSea uses for:

- place weather responses
- route evidence
- captain questions
- station metadata
- BigQuery validation and archive rows

It is intentionally best-effort. If one source fails, the rest of the run
continues.

## Current source families

### 1. Puertos del Estado

Puertos del Estado is the main Spanish operational observation source.
PredSea currently ingests these network families:

- `REDEXT` offshore buoys
- `REDCOS` coastal buoys
- `REDMAR` tide gauges and sea-level context
- `HF_RADAR` surface currents

Puertos data is read through the official THREDDS/OPeNDAP catalog and the
datasets themselves provide the authoritative timestamps.

### 2. EMODnet Physics

EMODnet Physics is a second official observation family. It broadens coverage
beyond Spain and adds additional in-situ marine measurements where available.

PredSea ingests the EMODnet ERDDAP time-series datasets that map cleanly into
the canonical observation schema, including:

- wave height
- wave period
- wave direction
- wind speed
- wind direction
- current speed
- current direction
- current `u` / `v`
- sea temperature
- salinity
- sea level

### 3. Portus observations

Portus observations remain available as an additional layer for compatible
station observations and metadata. Portus predictions are a separate forecast
lane and are not part of the observation layer described here.

## ETL cadence

The hourly ETL run refreshes the observation layer and the validation archive.
PredSea’s scheduled workflow runs hourly at `:30` UTC.

Within each run, the observation ETL is built to be additive:

1. Discover sources.
2. Fetch source datasets.
3. Normalize measurements into long-format rows.
4. Build station metadata rows.
5. Write validation JSONL artifacts.
6. Export normalized rows to BigQuery when configured.

If a source is unavailable, the run keeps going with the sources that did work.

## Timestamp rules

PredSea never invents observation timestamps.

For Puertos del Estado, the dataset’s own time coordinate is the source of
truth:

- `ds.TIME` or the dataset’s equivalent time coordinate is authoritative
- do not replace it with file names, ingestion time, or run date
- future timestamps are preserved and flagged rather than silently invented

For EMODnet Physics, the dataset time column is authoritative in the same way.

For the normalized BigQuery rows, the canonical timestamps are:

- `sample_time_utc`
- `observed_at_utc`
- `source_time_coordinate_utc`
- `ingested_at_utc`

The local validation archive also keeps `collected_at_utc` so the ETL can
distinguish source time from run time before export.

## Sampling and normalization

PredSea stores observations in **long format**. Each row represents one
variable at one sampled time for one station.

The canonical observation row keeps:

- `provider`
- `network`
- `station_id`
- `station_name`
- `latitude`
- `longitude`
- `variable`
- `value`
- `units`
- `sample_time_utc`
- `observed_at_utc`
- `source_time_coordinate_utc`
- `qc_flag`
- `freshness_status`
- `freshness_state`
- `quality_score`
- `is_future_timestamp`
- `dataset_url`
- `source_label`

The ETL also writes station metadata rows with:

- `station_kind`
- `priority`
- `variables_supported`
- `nearest_routes`
- `distance_to_route_nm`
- `distance_to_palma`
- `distance_to_ibiza`
- `distance_to_menorca`

## Canonical variables saved

PredSea normalizes source-specific fields into a shared variable vocabulary.
The current canonical observation variables include:

- `sea_level`
- `sea_level_residual`
- `wave_height`
- `wave_height_max`
- `wave_period_peak`
- `wave_period_mean`
- `wave_direction`
- `wave_peak_direction`
- `swell_1_height`
- `swell_2_height`
- `wind_speed`
- `wind_direction`
- `air_temperature`
- `water_temperature`
- `salinity`
- `sea_level_pressure`
- `air_pressure`
- `current_speed`
- `current_direction`
- `current_u`
- `current_v`
- `depth`

Not every source provides every variable. The ETL preserves only what the
source actually exposed.

## What each source usually contributes

### Puertos del Estado

Typical variables by network:

- `REDEXT`
  - wave height
  - wave period
  - wave direction
  - wind speed
  - wind direction
  - sea temperature
  - current speed
  - current direction

- `REDCOS`
  - coastal wave metrics
  - wind speed
  - wind direction
  - pressure
  - temperature
  - current variables when available

- `REDMAR`
  - sea level
  - tide-related context
  - sea-level residuals when available

- `HF_RADAR`
  - current speed
  - current direction
  - east-west current component
  - north-south current component

### EMODnet Physics

Common EMODnet Physics observations currently mapped by PredSea include:

- significant wave height
- wave period
- wave direction
- wind speed
- wind direction
- current speed
- current direction
- current `u` / `v`
- water temperature
- salinity
- sea level

## Where the data goes

### Local ETL artifacts

Each run writes validation artifacts under:

`outputs/YYYY-MM-DD/runs/RUN_ID/validation/`

The most useful files are:

- `observation_samples.jsonl`
- `forecast_index.jsonl`
- `station_metadata.jsonl`
- `matched_validation.jsonl`
- `validation_summary.json`

### BigQuery

The normalized observation rows are exported to:

- dataset: `predsea_validation`
- table: `evidence_rows`

Station metadata rows are exported to:

- dataset: `predsea_validation`
- table: `station_metadata`

## How to access observations through the API

PredSea does not currently expose a raw `/observations` listing endpoint.
Instead, observations are surfaced through the weather and evidence endpoints.

### 1. Place weather

Use place weather when you want the current observation-backed weather package
for a named location:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/places/palma/weather?date=2026-06-19&run=latest"
curl "https://predsea-api-193957983101.europe-west1.run.app/places/ibiza/weather?date=2026-06-19&run=latest"
```

### 2. Location weather

Use location weather when you have raw coordinates rather than a place ID:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/locations/weather?date=2026-06-19&run=latest&latitude=39.52&longitude=2.58"
```

### 3. Route evidence

Use route evidence when you want the observation and forecast context behind a
passage:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/evidence?date=2026-06-19&run=latest"
```

### 4. Route briefing

Use briefing when you want the captain-facing summary:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/briefing?date=2026-06-19&run=latest&vessel_class=medium&format=whatsapp"
```

### 5. Route question

Use the question endpoint when you want a more conversational answer grounded
in the stored evidence:

```bash
curl -X POST "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/question" \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-06-19",
    "run": "latest",
    "question": "How are the observations on this route today?",
    "vessel_class": "medium"
  }'
```

## Regions currently covered

The observation layer is national rather than Balearics-only.

In practice, the current Puertos and EMODnet ingestion can cover:

- the Balearic Islands
- the Spanish mainland coast
- the Canary Islands
- the Strait of Gibraltar and nearby Atlantic / Mediterranean edges
- broader European waters where EMODnet Physics exposes valid datasets

That means the observation layer includes both the local PredSea operating
area and a wider observation footprint, which helps keep the archive rich.

## Reliability rules

The observation ETL is designed to keep going when one source fails.

This means:

- Puertos failures do not stop EMODnet ingestion
- EMODnet failures do not stop Puertos ingestion
- Portus failures do not stop either
- forecast work still proceeds even if one observation family is empty

PredSea’s goal is to keep the observation archive as complete as possible
without letting one brittle upstream source take the whole run down.
