# PredSea API and WhatsApp guide

This guide explains how to use the API outputs and what the WhatsApp agent should expect from them.

## Core behavior

PredSea is a local marine briefing assistant, not an autopilot or a replacement for official forecasts. The captain owns the final decision.

The API now returns one canonical `operational_stance` per route/run/question context so the visible answer, briefing, and follow-up questions stay consistent.

## Guaranteed minimum surface

PredSea guarantees these core user-facing surfaces:

- daily briefing
- route questions
- place weather for named locations and optional coordinates

The contract for those surfaces is:

- **daily briefing**: a stable morning summary that anchors the day
- **route questions**: operational answers for passage planning and follow-ups
- **place weather**: wave, swell, wind, current, and freshness for a place or coordinate
- **place hierarchy**: `palma` is the default Palma place, while `port_de_palma`, `port_adriano`, and `can_pastilla` are separate places
- **static place metrics**: distance and typical travel time come from a fixed place-pair table first, then fall back to a graph-based sea route for uncatalogued pairs
- **coordinate distance**: `/places/distance/coordinates` returns maritime sea-route distance and a travel-time estimate for raw latitude/longitude pairs
- **route geometry**: `/places/route/{origin}/{destination}` returns navigable waypoints and accepts raw coordinate overrides on day one. Pass `origin_latitude`, `origin_longitude`, `destination_latitude`, and `destination_longitude` when you want to route from exact locations instead of place names. The response also includes a `checkpoints` array with local ETA and sampled weather at each in-route point, and each checkpoint weather block uses `sample_time_local` so the WhatsApp layer can talk about timing along the passage without re-deriving the route.
- **route answers**: include the same distance basis in the response JSON for route planning questions
  - when available, water temperature and air temperature are included too

Anything beyond that remains additive, not required for the minimum supported product.

## Response style

Visible answers should:

- speak in windows, not minutes
- use Europe/Madrid local time in the user-facing text
- avoid safety absolutes like `safe`, `guaranteed`, or `no issues`
- keep the default answer short and operational
- expand only when the captain asks `why?` or requests evidence

Typical answer sections:

- Current
- Trend
- Windows
- Comfort
- Watch out
- What could change
- Confidence

## Important fields returned by the API

### `operational_stance`

Shared internal summary used by the API and the WhatsApp agent.

### `evidence_used`

Shows the evidence behind the call, including:

- forecast variables used
- hourly points considered
- route segments
- observation alignment
- forecast sanity checks
- passage evidence

### `freshness_status` / `freshness_warning`

Helps the API tell the captain when the latest package is still from the previous run or should be rechecked before departure.

## WhatsApp integration notes

The WhatsApp layer should use the same canonical stance as the API and should not re-derive its own recommendation. It should render the answer from the API stance, then optionally add a short human-friendly wrapper.

## Common question types

- Daily briefing summary
- Departure timing
- Comfort / risk
- Route conditions
- What changed since the last check
- Position-aware passage questions
- Anchoring guidance from a GPS point
- What is the swell / wave / weather in a named place now?

## Current source coverage

The ETL that feeds the API and WhatsApp currently uses:

- Copernicus Mediterranean waves and currents
- SOCIB via `api.socib.es`
- Puertos del Estado / REDEXT
- Portus observation and model-point data

## Local testing

Use the API question endpoint for the canonical answer, and compare it to the WhatsApp renderers if you want to inspect how the same stance is phrased in the chat surface.
