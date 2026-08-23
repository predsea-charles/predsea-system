# Puertos del Estado Observation Layer

PredSea uses a source-specific Puertos observation layer with separate connectors for:

- `REDEXT` for offshore buoys
- `REDCOS` for coastal buoys
- `HF_RADAR` for surface currents
- `REDMAR` for sea-level and tide context only

## Timestamp rules

PredSea never treats the last timestamp in a file as automatically valid.
Each observation is accepted only if:

- the value is non-null
- the value is not a fill value
- the source time is not in the future beyond the allowed tolerance
- QC is good when QC data is present

Future timestamps are marked as `future` and excluded from the live observation layer.

## Normalized observation fields

The canonical observation rows keep:

- `provider`
- `network`
- `station_id`
- `station_name`
- `variable`
- `value`
- `units`
- `sample_time_utc`
- `observed_at_utc`
- `source_time_coordinate_utc`
- `qc_flag`
- `freshness_status`
- `quality_score`

## Source priorities

Operationally, PredSea prefers:

1. SOCIB
2. REDEXT
3. REDCOS
4. HF_RADAR
5. Portus
6. REDMAR for sea level only
7. Copernicus forecast as fallback

## Station metadata

Each discovered station carries route-aware metadata so the ETL can keep the
validation layer and the API aligned:

- `station_kind`
- `variables_available`
- `priority`
- `nearest_routes`
- `distance_to_route_nm`

That metadata is written into the validation archive and exported to BigQuery
alongside the observation rows.
