# SOCIB API Migration Design

## Goal

Replace the deprecated SOCIB `apps.socib.es/DataDiscovery` observation path with the modern `https://api.socib.es/` API across PredSea ETL.

This is a hard migration:

- `DataDiscovery` is removed from the active observation flow
- `api.socib.es` becomes the only SOCIB source for automated ETL
- the rest of the ETL continues to work unchanged

The new flow should support:

1. **Platform discovery**
2. **Data-source discovery**
3. **Latest observations**
4. **Historical observation windows**
5. **Metadata caching**

## Design Choice

Keep the current flat-module ETL style and migrate the SOCIB implementation in place rather than introducing a package refactor.

Reason:

- fastest path
- smallest import churn
- minimal impact on the working ETL
- easiest to wire into the existing observation ingestion step

## Scope

### In Scope

- Replace `apps.socib.es/DataDiscovery/list-moorings`
- Add a new `api.socib.es` client for automated ETL
- Discover SOCIB platforms by type
- Resolve instruments / data sources from platforms
- Fetch latest observation data from `data-sources/{id}/data/?latest=true`
- Fetch historical data with date windows when needed
- Cache platform and data-source metadata
- Cache raw JSON responses
- Preserve QC flags and missing-value handling
- Add retry / timeout / exponential backoff behavior
- Log endpoint, platform type, data-source id, query window, and row counts
- Integrate into the existing observation ingestion path
- Update tests for the new SOCIB flow

### Out of Scope for This Migration

- Rebuilding the broader ETL architecture
- Non-SOCIB source changes
- New API endpoints in PredSea
- New analytics dashboards
- BigQuery schema redesign

## New / Updated Modules

Add a new flat SOCIB API client family beside the existing ETL helpers:

- `socib_api.py`
- `socib_api_client.py`
- `socib_api_parsers.py`
- `socib_api_metadata.py`
- `socib_api_observations.py`

The existing `socib_public.py` DataDiscovery path should be retired from the active ETL flow once the new API path is wired in.

## Data Sources

### 1. Platform Discovery

Base URL:

`https://api.socib.es/`

Platform discovery should use the platform listing endpoints and filter by platform type.

Target platform types for the first migration:

- `Coastal Station`
- `Oceanographic Buoy`
- `Sea Level`
- `Weather Station`

The migration should use the API’s native discovery model instead of the old DataDiscovery moorings list.

### 2. Data Sources / Instruments

From platform discovery, resolve related instruments and data-source identifiers.

The ETL should treat these as the canonical bridge to observations.

### 3. Observations

Primary observation fetch pattern:

`/data-sources/{id}/data/?latest=true`

Historical window pattern:

`/data-sources/{id}/data/?initial_datetime=...&end_datetime=...`

Rules:

- prefer bounded date windows when historical data is requested
- preserve QC / quality flags if present
- preserve missing values without inventing data
- keep raw JSON snapshots for traceability

## Normalization Rules

The new SOCIB API client should normalize records into the same observation shape used by the ETL today, with enough metadata to support validation and route evidence.

At minimum keep:

- `source = "socib_api"`
- platform type
- platform id
- data-source id
- UTC timestamp
- variable values
- QC flags

If the API returns arrays or nested field names, normalize them in one parser layer so downstream code does not care about the source format.

## Module Responsibilities

### `socib_api_client.py`

Provides:

- retrying HTTP client
- `timeout = 120`
- `retries = 3`
- exponential backoff
- `api_key` / `apikey` support
- raw JSON caching helpers

### `socib_api_metadata.py`

Provides:

- platform discovery
- platform-type filtering
- caching of platform and data-source metadata
- mapping from platform -> instrument -> data-source ids

### `socib_api_parsers.py`

Provides:

- response normalization
- QC flag preservation
- missing-value handling
- timestamp normalization

### `socib_api_observations.py`

Provides:

- latest observation fetch
- historical observation fetch
- first-pass platform-type handling
- dry-run mode

### `socib_api.py`

Provides:

- a convenience wrapper that returns the full SOCIB observation bundle for the ETL

## ETL Integration

Replace the old DataDiscovery-based SOCIB path in the observation ingestion layer with the new `api.socib.es` flow.

Recommended sequence:

1. Discover platforms by the four target platform types
2. Resolve instruments / data-source ids
3. Fetch latest observations for the active ETL run
4. Fetch historical windows only when needed for validation or backfill
5. Cache raw JSON and metadata
6. Merge the normalized SOCIB observations into the existing observation bundle

The migration must be additive in behavior:

- if SOCIB API calls fail, the rest of the ETL continues
- other providers remain unaffected
- the ETL should still write its other artifacts even when SOCIB is unavailable

## Scheduling / Operational Requirements

Use:

- `timeout = 120`
- `retries = 3`
- `backoff_factor = 2`
- `page_size = 100`

Caching:

- cache platform metadata
- cache data-source metadata
- cache raw JSON responses
- reuse cached metadata when the discovery layer is temporarily unavailable

Logging:

- endpoint
- platform type
- platform id
- data-source id
- query parameters
- date window
- row counts
- cache path if written
- error summary on failure

## Error Handling

Behavior:

- transient failures should retry
- permanent failures should be logged and skipped
- SOCIB failure must not stop the rest of the ETL
- the code should not fall back to `apps.socib.es/DataDiscovery`

## Testing

Add tests for:

- platform-type filtering
- platform-to-data-source discovery mapping
- latest-data URL construction
- historical date-window URL construction
- QC flag preservation
- missing-value handling
- dry-run behavior
- retry / timeout handling where practical

At least one integration-style test should be skipped when `api.socib.es` is unreachable in CI.

## Success Criteria

The migration is successful if:

- the ETL no longer calls `apps.socib.es/DataDiscovery`
- SOCIB observations come from `api.socib.es`
- platform discovery and data-source resolution work
- latest and historical observation fetches work
- raw JSON is cached
- QC flags are preserved
- the ETL still completes when SOCIB is down
- the rest of the pipeline remains stable

