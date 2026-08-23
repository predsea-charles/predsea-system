# PredSea ETL overview

This document summarizes the current ETL and the data it produces for the API, BigQuery, and WhatsApp outputs.

## What the ETL does

Each hourly run:

1. Fetches forecast inputs and route evidence.
2. Ingests observations from the active marine sources.
3. Builds one canonical route snapshot per route.
4. Produces briefing artifacts, validation JSONL files, and map/evidence outputs.
5. Exports normalized validation rows to BigQuery when configured.

The current scheduled workflow runs hourly at `:49` UTC.

## Current observation sources

The ETL now combines observations from:

- SOCIB via `https://api.socib.es/`
- Puertos del Estado via the official THREDDS/OPeNDAP catalogue at `https://opendap.puertos.es/`
- Portus observation time series

The ETL keeps observations best-effort. If one source is unavailable, the run continues with the remaining sources.

## Portus

Portus is integrated as a first-class observation branch with:

- station/buoy time series parsing
- model-point discovery
- latest-position model data
- QC flag preservation
- raw JSON caching

## Puertos del Estado

Puertos del Estado observations now come from the official THREDDS/OPeNDAP NetCDF catalogue. The connector discovers all tide-gauge station catalogs exposed by Puertos, reads explicit NetCDF time coordinates, and normalizes the latest sample per supported variable.

The source keeps timestamps source-specific:

- `sample_time_utc` comes from the dataset time coordinate
- `observed_at_utc` mirrors the same source timestamp
- `ingested_at_utc` is only when PredSea stored the row

The first supported variables are sea level and depth, with more source-specific variables added as the station catalogs expose them.

## BigQuery export

The validation archive exports into:

- dataset: `predsea_validation`
- table: `evidence_rows`

The table is normalized and includes:

- `record_type` (`forecast` or `observation`)
- `run_id`
- `run_date`
- `ingested_at_utc`
- source/station metadata
- route/variable/value metadata
- forecast and observation source timestamps

## Source freshness

Useful freshness fields:

- `ingested_at_utc`: when the ETL wrote the row
- `observed_at_utc`: when the station sample was observed
- `source_time_coordinate_utc`: the raw time coordinate reported by the source
- `freshness_state`: `LIVE`, `RECENT`, `AGING`, `STALE`, or `FUTURE`
- `forecast_created_at_utc`: when the forecast row was issued

## Local time

Visible API output should use Europe/Madrid local time and window language. UTC is kept in technical evidence only.

## Recommendation state

The API keeps one canonical operational stance per route/run context so follow-up questions, briefing text, and WhatsApp replies stay consistent.

## Docs to read next

- `api/README.md`
- `docs/bigquery-evidence-rows.md`
- `docs/superpowers/specs/2026-06-11-predsea-response-and-socib-cutover.md`
