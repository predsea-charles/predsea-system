# Project PredSea: Decision Intelligence for the Sea

## Vision

PredSea is a human-in-the-loop maritime decision intelligence system for the
Balearic Islands.

The product does not try to be another generic weather app. Captains already
have access to marine forecasts, wind maps, and dashboards. PredSea translates
ocean forecasts, SOCIB buoy truth, route exposure, vessel context, and human
review into concise operational decisions.

Core positioning:

```text
Ocean data is everywhere.
Operational decisions are not.
```

## Product Principle

PredSea should own decision intelligence, not raw data.

Every output should help answer at least one captain question:

- Can I go?
- When should I leave?
- Which part of the route is exposed?
- Will it feel worse than the wave height suggests?
- Should smaller vessels wait?
- Is this route workable, conservative, or restricted?

If a metric, map layer, or paragraph does not support one of those decisions, it
should stay out of the captain-facing message.

## Current MVP

The working MVP lives in `humanintheloop/`.

It combines:

- Copernicus Marine Mediterranean wave and surface-current forecasts.
- SOCIB public buoy observations.
- Route-specific sampling for initial Balearic routes.
- Vessel-class thresholds for `small`, `medium`, and `large` vessels.
- Human review before publishing or sending advice.
- WhatsApp-style and LinkedIn-ready artifacts.

The MVP is intentionally pragmatic. It proves whether route-specific
interpretation is useful before investing in a full production chat system,
owned NEMO/SWAN modeling, or large-scale lakehouse storage.

## Map Priority

Maps are now the next product priority.

The map should not look like an optimal-route instruction. It should be an
Oceanographic Conditions Map: visual evidence that lets the captain inspect the
sea state before reading PredSea's operational interpretation.

First map outputs should focus on oceanic prediction:

- Significant wave height.
- Wave direction.
- Surface current speed.
- Surface current direction.
- Full Balearic forecast-region context.
- Route status: favorable, workable, conservative, or restricted.

Current MVP implementation:

- `humanintheloop/map_generator.py` creates first-version Oceanographic
  Conditions Maps without route overlays.
- The daily ETL writes `route_decision_map.png` for each configured route.
- The first version uses a lightweight Pillow renderer over the existing
  Copernicus NetCDF grid, so it works in GitHub Actions without Cartopy.
- The current map view uses the full Copernicus Mediterranean 4.2 km forecast
  grid available to the MVP, with schematic island labels as geographic context.
- `scripts/generate_ocean_conditions_map.py` is the preferred publication-map
  script when real coastline detail is needed. It uses Cartopy coastline/land
  features, latitude/longitude axes, a real colorbar, and optional current
  vectors.
- These maps are operational visual snippets, not final cartographic products.

Wind can be included only when it changes the operational interpretation, for
example:

- Wind against current.
- Wind aligned with swell.
- Afternoon sea breeze reducing comfort.
- Exposed channels where wind direction explains why conditions may feel worse.

PredSea should not compete with wind apps on wind visualization. Wind is
supporting context; the core value is ocean route decision intelligence.

## Communication Style

PredSea should sound like an experienced maritime operations desk:

- Calm.
- Concise.
- Operational.
- Honest about uncertainty.
- Human reviewed.

Avoid:

- Hype.
- Generic weather summaries.
- Excessive technical detail.
- Claims that are not supported by validation.
- Saying PredSea beats another model unless a separate baseline comparison
  exists.

## Near-Term Product Direction

The next useful product step is not Snowflake, Iceberg, or multi-agent
architecture.

The next useful product step is:

```text
forecast + buoy truth + route exposure + vessel class + oceanographic evidence map
= captain-ready operational guidance
```

The daily artifacts should evolve toward:

- Morning briefing.
- Afternoon/evening update.
- Oceanographic Conditions Map per route.
- Balearic overview conditions map.
- WhatsApp-style captain interaction.
- LinkedIn-ready operational summary.
