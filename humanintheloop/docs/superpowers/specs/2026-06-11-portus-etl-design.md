# Portus ETL Design

## Goal

Add Puertos del Estado / Portus as a new evidence source in PredSea with two branches:

1. **Observations** from the public `StationData` JSON endpoint.
2. **Predictions/model points** from the public `puntosMalla` discovery and `lastData/positions/{id}` endpoint family.

The first version should fit the current flat-module ETL style and avoid a repo-wide refactor. The goal is to get useful Portus data into the evidence layer quickly, while preserving raw JSON, QC flags, and model-point metadata for later expansion.

## Design Choice

Use the current module style already present in the repo rather than introducing a new `src/etl/puertos/` package layout.

Reason:

- fastest path
- least import churn
- least risk to the working ETL
- easiest to wire into existing `ingest_observations.py` and pipeline code

The package-style refactor can happen later if Portus grows substantially.

## Scope

### In Scope

- Public Portus observation endpoint parsing
- Public model-point discovery
- Public latest model/position fetch
- Raw JSON caching
- Normalized observation and prediction rows
- QC flag preservation
- Logging of endpoint, station/model code, date range, and row counts
- Retry/backoff/timeout behavior for transient failures
- ETL integration through the existing observation ingestion path
- Tests for parsing and dry-run behavior
- First-pass observation parameters for wave, wind, current, and temperature variables

### Out of Scope for First Pass

- Full route intelligence based on Portus model points
- ETL package restructuring into a new `src/etl/puertos/` tree
- New API endpoints
- BigQuery schema changes specific to Portus

## New Modules

Add the following flat modules beside the existing ETL helpers:

- `portus_config.py`
- `portus_client.py`
- `portus_parsers.py`
- `portus_stations.py`
- `portus_observations.py`
- `portus_predictions.py`

Optional integration helper:

- `fetch_puertos_portus.py` or a small extension to `ingest_observations.py` if the team prefers to keep the original helper name stable

## Data Sources

### 1. Observations

Endpoint:

`https://poem.puertos.es/portus/StationData`

Example:

`https://poem.puertos.es/portus/StationData?code=3545&params=Hm0,Hmax,Tm02,Tp&from=20260522@0000&to=20260612@0000`

Expected response:

```json
[
  ["UTC", "Hm0 (m)", "Hmax (m)", "Tm02 (s)", "Tp (s)"],
  [
    [1779408000, [0.2, 1], [0.35, 1], [3.33, 1], [5.22, 1]]
  ]
]
```

Rules:

- preserve QC flags as separate fields
- treat `-9999.9` as missing
- keep raw JSON cache
- convert timestamps to UTC-aware datetimes during normalization
- include the first observation pass for wave, wind, current, and temperature fields whenever the endpoint exposes them

Normalized names for the first scope:

- `Hm0 (m)` -> `hs_m`
- `Hmax (m)` -> `hmax_m`
- `Tm02 (s)` -> `tm02_s`
- `Tp (s)` -> `tp_s`
- wind variables -> normalized wind speed / direction fields
- current variables -> normalized current speed / direction fields
- temperature variables -> normalized temperature fields

### 2. Predictions / Model Point Discovery

Discovery endpoint:

`https://portus.puertos.es/portussvr/api/puntosMalla/portus/pred/Cirana?verif=true`

Observed response fields:

- `longitud`
- `latitud`
- `id`
- `modelo`
- `tipo`
- `codigoEstacion`
- `region`
- `tdelta`
- `tunidad`

Store normalized metadata fields:

- `model_point_id`
- `model_name`
- `lat`
- `lon`
- `region`
- `station_code_for_verification`
- `time_step`
- `time_unit`

Latest prediction endpoint:

`https://portus.puertos.es/portussvr/api/lastData/positions/{id}`

First pass should:

- fetch the latest JSON
- cache the raw response
- parse useful fields into normalized rows or metadata records
- keep the model-point identity attached

## Module Responsibilities

### `portus_config.py`

Contains:

- endpoint URLs
- default timeout
- retry policy settings
- observation parameter list
- normalization map
- station/model point allowlists if needed

### `portus_client.py`

Provides:

- retrying HTTP client with exponential backoff
- `timeout = 60`
- helper methods for GET requests
- raw JSON caching helpers
- structured logging helpers for endpoint, station code, model point id, date range, and row count

### `portus_parsers.py`

Provides:

- `normalize_variable_name(raw_name)`
- `parse_station_data(payload, station_code)`
- `parse_model_points(payload)`
- `parse_last_positions(payload, model_point_id, station_code_for_verification=None)`

The parser must:

- keep QC flags
- convert missing values to `None`
- return a normalized `DataFrame` or list of normalized records

### `portus_stations.py`

Provides:

- a small mapping of station codes used by PredSea
- optional route relevance metadata for later use

This module should stay small and declarative.

### `portus_observations.py`

Provides:

- recent observation fetch for a station code
- observation-range fetch for `now - 48h` to `now`
- dry-run mode
- normalized output + raw cache path

### `portus_predictions.py`

Provides:

- model-point discovery
- latest model position fetch by `id`
- optional daily metadata snapshot generation

## ETL Integration

Integrate Portus through the existing observation pipeline first.

Recommended sequence:

1. `ingest_observations.py` calls Portus observations alongside SOCIB / existing observations.
2. Portus prediction/model points are fetched in the same pipeline run or as a separate helper called by the pipeline.
3. Both branches contribute to the same evidence package lineage.

The first version should be additive:

- if Portus fails, the ETL continues
- other sources remain unaffected

## Evidence Handling

Save both:

- raw JSON payloads
- normalized records

Do not discard QC flags.

For normalized records, keep at least:

- `source = "puertos_portus"`
- station/model identifiers
- UTC time
- variable values
- QC flags

## Logging Requirements

Each fetch should log:

- endpoint
- station code or model point id
- date range or query parameters
- rows returned
- cache path if written
- error summary if the endpoint fails

## Error Handling

Use:

- `timeout = 60 seconds`
- `retries = 3`
- exponential backoff

Behavior:

- transient errors should retry
- permanent errors should be logged and skipped
- the ETL should continue without Portus if the endpoint is down

## GitHub Actions / Scheduling

Recommended scheduling for the first pass:

- hourly or every 3 hours for latest prediction/model data
- every 3 hours or every 6 hours for observations, depending on cost and availability
- once daily for model-point discovery metadata

Suggested operational flow:

1. Fetch recent observations from `now - 48h` to `now`
2. Fetch model-point metadata daily
3. Fetch latest position/model data hourly
4. Cache raw JSON
5. Write normalized rows to the ETL output layer

## Testing

Add tests for:

- observation payload parsing
- QC flag preservation
- missing-value conversion
- model-point discovery parsing
- latest position parsing
- dry-run behavior
- retry/timeout behavior where practical

At least one integration-style test should be skipped if the Portus endpoint is unreachable in CI.

## Success Criteria

The first implementation is successful if:

- Portus observations can be fetched and normalized
- Portus model points can be discovered and stored
- Portus latest model data can be fetched by point id
- raw JSON is cached
- QC flags are preserved
- the ETL continues even if Portus is down
- the current pipeline still works for existing sources
