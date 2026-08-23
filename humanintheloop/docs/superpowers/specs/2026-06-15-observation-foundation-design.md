# Observation Foundation Design

## Goal

Build a trustworthy observation foundation for PredSea using source-specific
connectors and explicit timestamps.

The foundation must make PredSea the single source of truth for observation
data consumed by the API, WhatsApp, route briefings, and validation. It should
stop future-dated rows from leaking into the live layer and keep the source
provenance visible all the way through normalization.

## Background

PredSea already ingests observations from multiple sources, but the current
Puertos del Estado branch showed why the foundation needs stronger boundaries:

- source-specific timestamp rules matter
- not every NetCDF time coordinate is a usable live observation time
- a single branch should not be able to poison the entire ETL

The next step is to formalize an observation foundation that is strict about
time, explicit about provenance, and flexible enough to support later fusion.

## Core Principle

Treat each observation source as independent.

Each connector must:

- parse its own source format
- assign timestamps explicitly from the source data
- reject or quarantine future-dated rows
- normalize into the same canonical schema

The ETL should never guess observation time from ingestion time.

## Scope

### In Scope

- Source-specific connectors for:
  - SOCIB
  - REDEXT
  - REDCOS
  - REDMAR
- Independent connector branches so one source can fail without stopping the
  whole ETL.
- A unified observation schema for all normalized rows.
- Explicit timestamp handling with:
  - `sample_time_utc`
  - `observed_at_utc`
  - `ingested_at_utc`
  - `source_time_coordinate_utc`
- Freshness states that can distinguish live data from future-dated data.
- A station metadata table inside PredSea.

### Out of Scope

- Observation fusion and source prioritization across sources.
- HF radar connector work.
- Portus connector redesign beyond the existing observation foundation.
- Route solver changes.

## Source Set

Phase 1 includes:

- SOCIB
- REDEXT
- REDCOS
- REDMAR

REDMAR is included as a specialized sea-level source only.

REDMAR tide gauges should not be treated as the primary observation source for
navigation decisions.

## Connector Model

Create independent connectors for each source:

- `socib_connector`
- `redext_connector`
- `redcos_connector`
- `redmar_connector`

Each connector owns:

- catalog discovery
- variable parsing
- timestamp extraction
- quality flag handling where available
- normalization into the shared observation schema

Failure in one connector must be logged and quarantined without blocking the
other source branches.

## Timestamp Rules

The foundation must distinguish:

- `source_time_coordinate_utc` - the timestamp coordinate read from the source
- `sample_time_utc` - the actual measurement time used for the canonical row
- `observed_at_utc` - the time the observation should be treated as observed
- `ingested_at_utc` - when PredSea ingested the row

These are not interchangeable.

### Strict Rule

Never set `observed_at_utc = ingested_at_utc`.

### Future-Dated Rows

If a candidate observation timestamp is later than the current UTC time plus a
small tolerance window, PredSea must not surface it as a live observation row.

The row should be rejected or quarantined rather than rewritten into a false
“current” observation.

### Validity Strategy

For each variable and station:

1. evaluate the time coordinate explicitly
2. apply fill-value and null checks
3. apply QC checks when present
4. reject future timestamps for the live observation layer
5. select the most recent valid sample only after the above checks

The foundation must not rely on `time[-1]` as a proxy for the latest valid
measurement.

## Unified Observation Schema

Normalize each accepted row into a canonical observation record containing:

- `provider`
- `network`
- `station_id`
- `station_name`
- `variable`
- `value`
- `units`
- `source_field`
- `source_time_coordinate_utc`
- `sample_time_utc`
- `observed_at_utc`
- `ingested_at_utc`
- `qc_flag`
- `freshness_state`
- `latitude`
- `longitude`
- `depth_m`
- `is_future`
- `is_qc_good`

The same schema should work across all observation sources.

## Freshness States

Replace the current simple freshness labels with explicit states:

- `LIVE`
- `RECENT`
- `AGING`
- `STALE`
- `FUTURE`

Suggested interpretation:

- `0-2h` -> `LIVE`
- `2-6h` -> `RECENT`
- `6-12h` -> `AGING`
- `12-24h` -> `STALE`
- future-dated -> `FUTURE`

Future rows should carry a confidence penalty and must not be treated as live
observations.

## Station Metadata Table

Create a PredSea-managed station metadata table:

- `predsea_validation.station_metadata`

It should store:

- `provider`
- `network`
- `station_id`
- `station_name`
- `lat`
- `lon`
- `station_kind`
- `priority`
- `variables_supported`
- `distance_to_palma`
- `distance_to_ibiza`
- `distance_to_menorca`

This table is the place where PredSea learns which stations exist, where they
are, and which ones matter most operationally.

## Network Expectations

### SOCIB

SOCIB remains part of the observation foundation and continues to provide
Balearic-relevant marine observations where available.

### REDEXT

REDEXT is the offshore buoy branch.

Use it for:

- wave height
- wave period
- wave direction
- wind speed
- wind direction
- sea surface temperature
- current speed
- current direction

### REDCOS

REDCOS is the coastal buoy branch.

Use it for the same wave and meteorological fields as REDEXT where available.

### REDMAR

REDMAR is the sea-level branch.

Use it only for:

- sea level

Do not promote REDMAR tide gauges into the primary navigation-observation role.

## Error Handling

- If one source fails, the others should continue.
- If a source timestamp is missing or future-dated, reject or quarantine that
  row rather than forcing it into the live layer.
- If QC is present and indicates a bad sample, do not treat it as a live
  observation.
- If a source cannot be normalized cleanly, log the failure with the source
  label and station identity.

## Testing

Add tests for:

- source-specific timestamp parsing
- rejection of future-dated observation rows
- normalization into the unified schema
- REDMAR sea-level-only behavior
- independent connector failures not blocking the other branches
- station metadata storage and lookup

## Success Criteria

After implementation:

- PredSea has source-specific observation connectors for SOCIB, REDEXT,
  REDCOS, and REDMAR.
- Future-dated observation rows no longer appear as live observations.
- Each normalized observation row carries explicit source provenance.
- The unified schema is stable enough for later fusion and quality scoring.
- REDMAR remains a sea-level source, not a primary navigation source.

