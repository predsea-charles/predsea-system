# Place Hierarchy and Static Metrics Design

## Goal

Make PredSea’s place model more useful for marine operations by adding two things:

1. A **place hierarchy** where broad places can contain more specific ports or anchorages.
2. A **static metrics layer** for values that do not change often, such as distance and typical travel time between places.

This should let PredSea answer questions like:

- "Palma"
- "Port de Palma"
- "Port Adriano"
- "Can Pastilla"
- "What is the distance between Palma and Portocolom?"
- "How long does that usually take by yacht?"

The model should remain **place-first** for local weather and observations, while still supporting route-like facts that can be reused across the API and briefing layers.

## Core Principles

- PredSea should expose real named places and ports, not a single overloaded "Palma" object.
- `palma` should remain the default Palma place when a user asks about Palma without a more specific port.
- Specific ports inside Palma should be exposed as separate `place_id`s.
- Distances and typical travel times should be precomputed and treated as static facts.
- Observations should remain station-first and place-second.
- The resolver should choose the best available observation station for a place from an explicit candidate list.

## Scope

### In Scope

- Add a place hierarchy with Palma as the parent area and several named sub-ports.
- Expose specific Palma ports as separate place IDs.
- Keep `palma` as the default general Palma place.
- Add a static metrics table for distance and typical passage time between places.
- Support a hybrid observation mapping model:
  - explicit candidate station lists per place
  - broad station catalog across the Balearics and western Mediterranean
  - deterministic fallback order inside each place’s candidate list
- Keep weather and observation lookup separate from static metrics lookup.
- Update the API and ETL contracts so place weather can still work without recomputing static facts.

### Out of Scope

- Route recommendation redesign
- Daily briefing wording changes
- WhatsApp tone changes
- New forecast models
- New vessel threshold logic
- New map rendering logic

## Place Model

### Canonical Places

The following canonical `place_id`s should continue to exist:

- `ibiza`
- `palma`
- `formentera`
- `menorca`
- `cabrera`
- `ciutadella`
- `alcudia`
- `soller`
- `barcelona`
- `valencia`
- `portocolom`

### Palma as a Parent Place

`palma` should behave as the default general Palma place.

Specific ports in the Palma area should be exposed as separate place IDs, for example:

- `port_de_palma`
- `port_adriano`
- `can_pastilla`

The first implementation should keep the list small and practical. More sub-ports can be added later if they are useful operationally.

### Place Selection Behavior

When a user says:

- "Palma" -> use `palma`
- "Port de Palma" -> use `port_de_palma`
- "Port Adriano" -> use `port_adriano`
- "Can Pastilla" -> use `can_pastilla`

If a user gives only a broad place name, PredSea should choose the broad default place rather than guessing a sub-port.

## Static Metrics Layer

Some values should be precomputed because they rarely change:

- distance between places
- typical travel time between places
- optional route bearing / passage direction later if useful

These values should not be recomputed for every API request.

### Suggested Static Fields

For each place pair, store:

- `origin_place_id`
- `destination_place_id`
- `distance_nm`
- `typical_travel_time_minutes`
- `typical_speed_kn` when useful for deriving the time
- `computed_at_utc`
- `version` or `source_tag`

The static layer can later back the route briefing, route questions, and planning utilities.

## Observation Strategy

PredSea should remain **station-first** for observations:

- maintain a broad catalog of actual observation points
- include the Balearics and the western Mediterranean as far as useful
- attach places to an ordered list of candidate stations
- resolve the first station that has a usable fresh observation

This is preferable to pretending that each place is its own observation source.

### Station Resolution Rules

For each place:

1. Try the explicit station candidates in order.
2. Accept the first candidate with a usable observation block.
3. If none are usable, keep the place forecast-only.
4. Never invent an observation for a place that does not actually have one.

This keeps the output honest and explainable.

### Candidate Stations

The station catalog should include the best available entries from:

- SOCIB
- Puertos del Estado
- Portus

The actual candidate list for each place should be explicit and easy to read in code and tests.

## Initial Mapping Intent

The first implementation should support the following intent:

- `palma` should prefer Palma-area observations
- `port_de_palma`, `port_adriano`, and `can_pastilla` should prefer the best Palma-area or nearby coastal observations
- `portocolom` should prefer east-Mallorca or Portocolom-specific observation sources
- `barcelona` should prefer Barcelona-area observations
- `valencia` should prefer Valencia-area observations
- `soller` should prefer Sóller or the closest useful Mallorca observation sources

This mapping should be kept explicit so it can be revised as better stations become available.

## API and ETL Behavior

### API

The API should continue to expose:

- `/places/{place_id}/weather`
- route questions and briefings

The new place hierarchy should not break existing place-weather calls.

### ETL

The ETL should:

- produce place weather records for canonical places and ports
- use the static metrics table for distance / travel-time facts
- resolve place observations from explicit station candidates
- keep forecast and observation layers separate
- continue to preserve UTC and local-time fields

## Error Handling

- Unknown places should return a clear unsupported-place error.
- Missing observation candidates should fall back to forecast-only.
- Missing static metrics should not block the weather ETL.
- If a place has no meaningful observation source, the payload should say so by omission rather than guessing.

## Testing

Add tests for:

- Palma default place resolution
- Palma sub-port resolution
- static metrics lookup for a known place pair
- observation candidate ordering
- observation fallback when the preferred station is unavailable
- forecast-only behavior when no observation source exists

## Implementation Notes

This should be implemented in small steps:

1. Add the place hierarchy.
2. Add the static metrics table.
3. Add explicit observation candidate lists.
4. Update the place-weather resolver to use the new hierarchy.
5. Update tests and docs.

The design should stay simple enough that the API can explain it in one sentence:

> Palma is the default Palma place, specific ports are separate places, and observations come from the best station we know for each one.
