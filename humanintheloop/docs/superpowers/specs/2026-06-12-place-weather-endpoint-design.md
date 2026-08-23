# Place Weather Endpoint Design

## Goal

Add a place-based weather endpoint to PredSea so the API can answer questions like:

- "What is the swell and wave in Ibiza now?"
- "What is it near Palma tonight?"
- "What does the weather look like at my current position?"

This endpoint should be **weather-first** only.

It should provide:

- wave height
- wave direction
- swell height and direction
- wind
- current when available
- freshness metadata
- source metadata

It should **not** provide route recommendation logic yet.

## Design Choice

Use a **hybrid endpoint**:

- named places for human-friendly requests
- optional latitude / longitude for precise position-based use

This keeps the endpoint easy to share in morning briefings while still supporting live GPS usage later.

## Scope

### In Scope

- Add a place weather endpoint family
- Support named places such as Ibiza, Palma, Formentera, Menorca, Cabrera, Barcelona, and Valencia
- Support optional `lat` / `lon` overrides
- Normalize weather fields in the ETL into a place-based weather payload
- Preserve UTC timestamps and local-time display fields
- Preserve source and freshness metadata
- Keep the ETL weather-first and free of operational recommendation language
- Reuse the weather data later from the API and briefing layer

### Out of Scope

- Route recommendation changes
- Daily briefing redesign
- WhatsApp response redesign
- New vessel-threshold logic
- New map overlays
- New social / marketing renderers

## Proposed API Shape

The first version should be straightforward:

### `GET /places/{place_id}/weather`

Example:

```text
/places/ibiza/weather
/places/palma/weather
/places/formentera/weather
```

Optional query parameters:

- `lat`
- `lon`
- `date`
- `run`

If `lat` / `lon` are provided, the endpoint should use them as the primary lookup reference and treat `place_id` as a convenience label.

## Data Model

The ETL should emit a normalized weather record with fields like:

- `place_id`
- `place_name`
- `time_utc`
- `time_local`
- `timezone`
- `wave_height_m`
- `wave_direction_deg`
- `swell_1_height_m`
- `swell_1_direction_deg`
- `swell_2_height_m`
- `swell_2_direction_deg`
- `wind_kn`
- `wind_direction_deg`
- `current_kn`
- `current_direction_deg`
- `source`
- `source_system`
- `freshness_status`
- `freshness_warning`
- `observed_at_utc` when the row comes from an observation source

The first version should keep this purely factual.

No route advice, no "safe" language, and no captain decision text in the ETL output.

## Initial Place Catalog

Start with the places most useful for Balearics operations:

- Ibiza
- Palma
- Formentera
- Menorca
- Cabrera
- Barcelona
- Valencia

These are the first targets for the place weather lookup.

## ETL Behavior

The ETL should build the place weather layer from existing forecast and observation sources.

Recommended behavior:

1. Load forecast and observation inputs already available to the ETL.
2. Resolve each target place to a representative point or nearby grid sample.
3. Extract wave, swell, wind, and current values.
4. Normalize them into a place-weather record.
5. Persist raw source metadata and freshness information.
6. Make the output available to the API and briefing layer.

The ETL should remain best-effort:

- if one source is missing, the rest of the ETL continues
- missing values should remain missing
- QC / freshness metadata should be preserved

## Time Handling

Store:

- UTC timestamps always
- Europe/Madrid local time for display fields

The place weather layer should support both:

- technical evidence in UTC
- captain-facing display in local time

## Response Behavior

The endpoint should return weather information only.

It should answer:

- what the sea state is
- what the swell is doing
- what the wind is doing
- how fresh the data is

It should not yet answer:

- whether to leave now
- whether a route is comfortable
- whether the captain should wait

Those interpretations belong to the API briefing / question layer later.

## Error Handling

If a place lookup cannot be resolved:

- return a clear 404-style error
- say the place is unknown or unsupported

If the weather source is unavailable:

- return partial data when possible
- expose freshness / warning metadata
- avoid crashing the rest of the ETL

If `lat` / `lon` are outside the supported domain:

- fall back to the closest supported sample if appropriate
- otherwise report the position as unsupported

## Testing

Add tests for:

- named place resolution
- coordinate override behavior
- wave / swell / wind normalization
- missing-value handling
- freshness metadata
- local-time formatting
- ETL fallback behavior when one source is missing

## Implementation Note

This endpoint should be added as a weather layer only.

PredSea’s route recommendation and daily briefing layers can consume this place weather output later without changing the ETL contract.
