# PredSea Immediate Product Plan

## Goal

Move PredSea from a route-briefing MVP to a pilot-ready co-captain product while
keeping Matt's WhatsApp integration stable.

The product should answer captain questions from the latest environmental
evidence package. Briefings are no longer the center of the system.

## Product Contract

Keep the current API surface as much as possible:

```text
POST /routes/{route_id}/question
POST /question
GET  /routes/{route_id}/briefing
GET  /routes/{route_id}/media
GET  /maps
GET  /maps/inspect
```

`POST /routes/{route_id}/question` remains Matt's route endpoint.

`POST /question` is the location endpoint for shared GPS questions such as:

```text
I am here. Can I anchor tonight?
Can I stay here?
Where should I anchor near this position?
```

The request must include `latitude` and `longitude`. PredSea does not infer a
hidden position when those are missing.

## What Is Already Done

- The ETL fetches Copernicus and SOCIB as independent forecast sources.
- One slow source no longer blocks the whole ETL.
- The ETL generates Leaflet-ready map overlays and inspection grids.
- The API can sample a map grid with `/maps/inspect`.
- The API now has `POST /question` for Phase 1 location intelligence.
- The deployed API can answer a shared-GPS anchoring question using latest GCS
  map grids.

## Immediate Missing Pieces

The current GPS endpoint works, but it is using map overlays as an implicit
evidence source. The ETL needs to make location intelligence explicit.

Immediate changes:

1. Add a run-level `regional_evidence.json`.
2. Record supported modes: `route_question`, `location_question`, `map_inspect`.
3. Record available map variables, time coverage, bounds, and limitations.
4. Include regional evidence metadata in `run_manifest.json`.
5. Keep route artifacts for backward compatibility.
6. Improve API answers for relative dates such as "tomorrow morning".
7. Add confidence details based on freshness, horizon, variable availability,
   and domain coverage.

## Phase 1 ETL Evidence Contract

Each run should contain:

```text
outputs/<date>/runs/<run_id>/run_manifest.json
outputs/<date>/runs/<run_id>/regional_evidence.json
outputs/<date>/runs/<run_id>/maps/<variable>/index.json
outputs/<date>/runs/<run_id>/<route_id>/daily_snapshot.json
outputs/<date>/runs/<run_id>/sources/<source_id>/<route_id>/daily_snapshot.json
```

`regional_evidence.json` should contain:

```json
{
  "region_id": "western_mediterranean",
  "run_date": "2026-06-04",
  "run_id": "2026-06-04T1633Z",
  "supported_modes": ["route_question", "location_question", "map_inspect"],
  "available_variables": {
    "wave_height": {"units": "m", "time_count": 30, "bounds": [[38.5, 1.0], [40.5, 4.5]]},
    "current_speed": {"units": "m/s", "time_count": 30, "bounds": [[38.5, 1.0], [40.5, 4.5]]}
  },
  "limitations": [
    "No seabed type",
    "No depth/bathymetry",
    "No anchoring restrictions",
    "No nearby shelter search"
  ]
}
```

## Immediate Implementation Order

1. ETL: write `regional_evidence.json` from generated map indexes.
2. ETL: add `regional_evidence` metadata to `run_manifest.json`.
3. API: read `regional_evidence.json` when available.
4. API: include regional evidence metadata in `POST /question` responses.
5. API: fix "today/tomorrow" interpretation for route questions.
6. API: add `confidence_detail` to route and location answers.
7. Expansion: introduce `regions.json` before expanding to Mediterranean Spain.

## What Not To Do Yet

- Do not remove route endpoints.
- Do not remove route artifacts.
- Do not claim final anchoring recommendations.
- Do not expand to Atlantic Spain.
- Do not store huge NetCDF files as the primary API read path.

## Strategic Direction

The ETL prepares evidence. The API interprets evidence. The WhatsApp agent
delivers the co-captain experience.

PredSea should not claim to outperform numerical weather models. PredSea should
turn environmental data, local context, vessel context, and captain knowledge
into clear operational decisions.
