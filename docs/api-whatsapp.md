# PredSea API and WhatsApp Integration

This document describes the deployed PredSea API, how Matt's WhatsApp platform
should call it, how run-based evidence works, and what should be added next.

## Current Purpose

The API is the decision interface over stored PredSea evidence.

It does not download Copernicus, SOCIB, or model data during a captain request.
It reads the latest ETL evidence package from Google Cloud Storage and returns
captain-ready guidance. The captain-facing `answer` should read like a short
message from a maritime operations desk, not like a generic weather app or a
form response.

```text
WhatsApp platform
        -> PredSea API
        -> latest evidence package in GCS
        -> operational answer
```

## Production URL

Current Cloud Run URL:

```text
https://predsea-api-193957983101.europe-west1.run.app
```

Cloud Run service:

```text
predsea-api
```

Project:

```text
predsea-api
```

The API reads from:

```text
gs://predsea-daily-outputs/predictions
```

using these Cloud Run environment variables:

```text
PREDSEA_GCS_BUCKET=predsea-daily-outputs
PREDSEA_GCS_PREFIX=predictions
```

## Current Endpoints

Current route IDs:

- `addaia_fornells`
- `addaia_mahon`
- `alcudia_ciutadella`
- `alcudia_fornells`
- `andratx_ibiza`
- `andratx_san_antonio`
- `barcelona_palamos`
- `barcelona_tarragona`
- `cabrera_ibiza`
- `ciutadella_fornells`
- `formentera_palma`
- `fornells_mahon`
- `ibiza_formentera`
- `ibiza_mahon`
- `ibiza_san_antonio`
- `ibiza_soller`
- `palma_ibiza`
- `palma_barcelona`
- `palma_cabrera`
- `palma_ciutadella`
- `palma_mahon`
- `palma_valencia`

Canonical places:

- `addaia`
- `alcudia`
- `andratx`
- `barcelona`
- `cabrera`
- `can_pastilla`
- `ciutadella`
- `formentera`
- `fornells`
- `ibiza`
- `la_savina`
- `mahon`
- `menorca`
- `palamos`
- `palma`
- `port_adriano`
- `port_de_palma`
- `porto_portals`
- `san_antonio`
- `soller`
- `tarragona`
- `valencia`
- `west_ibiza`

Current map variables:

- `wave_height`
- `swell_1_height`
- `swell_1_direction`
- `swell_2_height`
- `swell_2_direction`
- `wind_wave_height`
- `wind_wave_direction`
- `current_speed`

Current vessel classes:

- `small`
- `medium`
- `large`

Current route-question parameters can include:

- `question`: required captain question.
- `date`: optional `YYYY-MM-DD`; omitted means latest available date.
- `run`: optional `latest` or a run ID such as `2026-06-09T1512Z`.
- `vessel_class`: optional, defaults to `medium`.
- `departure_time`: optional requested departure time, for example `08:30`.
- `priority`: optional, one of `comfort`, `safety`, or `schedule`.
- `current_latitude` and `current_longitude`: optional GPS position used for
  position-aware passage evidence.
- `location_label`: optional human-readable label.
- `current_time`: optional local time of the user request.
- `current_date`: optional local date of the user request.

### Health

```bash
curl https://predsea-api-193957983101.europe-west1.run.app/health
```

Response:

```json
{
  "status": "ok",
  "latest_date": "2026-05-31",
  "latest_run": "2026-05-31T0058Z",
  "storage_backend": "gcs"
}
```

`latest_run` can be `null` for older legacy daily folders that do not have
run-based outputs.

### Places

```bash
curl https://predsea-api-193957983101.europe-west1.run.app/places
```

This returns the canonical place registry with place IDs, display names,
coordinates, parent-child links, aliases, and observation candidates.

### Routes

Latest routes:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes"
```

Routes for a date:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes?date=2026-05-31"
```

Routes for a specific run:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes?date=2026-05-31&run=2026-05-31T0058Z"
```

### Evidence

Latest evidence for a route:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/evidence?run=latest"
```

Evidence for a specific date and run:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/evidence?date=2026-05-31&run=2026-05-31T0058Z"
```

The API currently returns the `decision_context` snapshot from `evidence.json`.
This keeps the existing `/briefing` and `/question` behavior stable while the
evidence package evolves.

### Briefing

WhatsApp format:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/briefing?run=latest&format=whatsapp&vessel_class=medium"
```

LinkedIn format:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/briefing?run=latest&format=linkedin&vessel_class=medium"
```

Supported query parameters:

- `date`: optional, `YYYY-MM-DD`
- `run`: optional, `latest` or a specific run ID
- `vessel_class`: `small`, `medium`, or `large`
- `format`: `whatsapp` or `linkedin`

### Question

Ask a captain-style question:

```bash
curl -X POST \
  "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/question" \
  -H "Content-Type: application/json" \
  -d '{
    "run": "latest",
    "question": "When is the best moment to leave from Palma to Ibiza today?",
    "vessel_class": "small",
    "departure_time": "10:00",
    "priority": "comfort",
    "location_label": "Palma Marina",
    "current_time": "09:30",
    "current_date": "2026-06-09"
  }'
```

Request fields:

- `question`: required captain question.
- `date`: optional `YYYY-MM-DD`; omitted means latest available date.
- `run`: optional. Use `latest` for the newest run of the selected date.
- `vessel_class`: optional, defaults to `medium`.
- `departure_time`: optional requested departure time.
- `priority`: optional operational priority, currently `comfort`, `safety`, or
  `schedule`.
- `current_latitude` and `current_longitude`: optional shared GPS position. If
  the position is close enough to the route, the decision engine uses it to
  focus on remaining passage segments. If it is far from the route, the answer
  warns that the position is not close enough and treats the question more
  conservatively.
- `location_label`: optional human-readable label.
- `current_time`: optional local time of the user request.
- `current_date`: optional local date of the user request.

Response includes:

- `answer`
- `intent`
- `date`
- `run`
- `evidence_timestamp`
- `freshness_status`
- `freshness_warning`
- `captain_knowledge`
- `evidence_used`

`evidence_used.sea_state` exposes the marine variables that support the answer,
including combined wave height, combined wave direction, route-relative sea
state labels, and swell or wind-wave component directions when the model source
provides them:

```json
{
  "sea_state": {
    "wave_height_m": {
      "min": 0.8,
      "max": 1.3,
      "peak_time": "14:00"
    },
    "wave_direction_deg": {
      "peak": 74.0,
      "hourly": [
        {
          "time": "10:00",
          "wave_direction_deg": 72.0,
          "wave_sea_state": "stern quartering sea"
        }
      ]
    },
    "components": {
      "swell_1": {"height_m": 0.8, "direction_deg": 45.0},
      "swell_2": {"height_m": 0.4, "direction_deg": 110.0},
      "wind_wave": {"height_m": 0.6, "direction_deg": 72.0}
    }
  }
}
```

The captain-facing `answer` should follow this hierarchy:

```text
Decision
Best window
Comfort
Risk
Why
What could change
Confidence
```

The API also returns structured fields for Relay AI, debugging, and future UI
explainability.

Example captain-facing answer:

```text
Decision: Palma -> Ibiza is workable today with conservative timing.

Best window: Leave before the exposed peak if possible; avoid the roughest
sampled period.

Comfort: Moderate. For this vessel size: use the calmest available window.

Risk: Low to moderate.

Why: The route sample shows lower wave height before the forecast peak, and
the worst segment is expected offshore.

What could change: a wind shift, swell timing change, or newer model run.

Confidence: Medium.
```

If confidence is unavailable in the evidence package, the API omits the
`Confidence:` line rather than printing a placeholder.

### Location Question

Ask from a shared GPS position:

```bash
curl -X POST \
  "https://predsea-api-193957983101.europe-west1.run.app/question" \
  -H "Content-Type: application/json" \
  -d '{
    "run": "latest",
    "question": "I am at this position, can I stay here tonight?",
    "latitude": 39.45,
    "longitude": 2.10,
    "vessel_class": "small",
    "location_label": "shared WhatsApp live location",
    "current_time": "19:00"
  }'
```

This is Phase 1 location intelligence. The request must include latitude and
longitude. It samples the nearest generated map grids, currently wave height,
current speed, and primary swell height. It is a screening layer, not final
anchoring clearance.

Known limitations returned by the API:

- no seabed type
- no depth or bathymetry
- no anchoring restrictions
- no nearby shelter search

### Maps

Get a Leaflet-compatible map overlay:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/maps?variable=wave_height&time=14:00&run=latest"
```

Response includes:

- `overlay_url`: PNG image overlay URL
- `bounds`: south, west, north, east
- `opacity`
- `units`
- `color_scale`
- `time`: closest forecast time actually selected
- `leaflet.method`: currently `L.imageOverlay`

Supported variables are the map variables listed at the top of this document.
If the requested time is not exactly available, the API returns the closest
available forecast overlay for that run.

Inspect one forecast value at a point:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/maps/inspect?variable=wave_height&time=14:00&run=latest&lat=39.57&lon=2.64"
```

Response includes:

- `value`
- `units`
- `sampled_lat`
- `sampled_lon`
- `inside_domain`
- `grid_indices`

### Media

Get route media URLs for WhatsApp, web, or download:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/media?run=latest"
```

Current public media artifacts:

- `route_decision_map.png`

Response includes `api_url`, optional `signed_url`, `download_url`, and
`media_type` for each artifact.

## Recommended WhatsApp Flow

Matt's platform can keep the first integration simple:

```text
captain message
        -> choose route_id
        -> POST /routes/{route_id}/question
        -> send answer text back to WhatsApp
```

Recommended default request:

```json
{
  "run": "latest",
  "question": "<captain message>",
  "vessel_class": "medium",
  "location_label": "shared location"
}
```

If the captain profile is known, Matt should pass the real `vessel_class`.

## Run Selection

Use `run=latest` for normal WhatsApp behavior.

Use a specific run only for debugging, validation, or replaying historical
answers.

```text
run=latest
run=2026-05-31T0058Z
```

If no run is supplied, the API also resolves the latest run when a run-based
folder exists. Explicit `run=latest` is clearer for Matt's integration.

## Supported Question Types

The route question endpoint currently handles:

- departure windows: "When should I leave?"
- go/no-go reads: "Is today a good day to cross?"
- route timing: "Can I cross tonight/tomorrow?"
- near-future conditions: "How will it be in four hours?"
- vessel comfort: "Would this feel comfortable for a 12m vessel?"
- fuel/current context: "Can I save fuel by using another route?"
- position-aware passage context when GPS is supplied

The location question endpoint currently handles:

- "Can I stay here?"
- "Is this position workable tonight?"
- first-pass anchoring screening from a shared GPS point

Questions that need seabed, bathymetry, local legal restrictions, marina
availability, or true alternate-route optimization should be answered
conservatively and identified as outside the current evidence package.

## Current API Limits

Important limitations:

- `/question` can screen a GPS point but cannot yet recommend the best nearby
  anchorage.
- The API does not calculate alternate routes yet.
- The API does not yet expose a stable `confidence_score: 0-100`; it exposes
  qualitative confidence and freshness metadata.
- The API does not yet expose a stable forecast-delta endpoint such as
  `/routes/{route_id}/changes?since=...`.
- Wind is not yet a default production decision variable unless atmospheric
  ingestion is enabled and evidence lineage confirms the wind source.
- Wave period and bathymetry are not yet in production evidence.

## Next Useful API Additions

The next high-value additions are:

- forecast-delta endpoint for "what changed since my last check?"
- numeric confidence score with a clear explanation
- richer waypoint/segment output for long passages
- map overlays for future wind variables once atmospheric ingestion is stable
- full evidence endpoint that exposes model comparison, not only the compact
  decision context

## SaaS / Webpage Integration

The webpage should not fetch forecasts directly. It should call the API.

Useful calls:

```text
GET /health
GET /routes?run=latest
GET /routes/{route_id}/evidence?run=latest
GET /routes/{route_id}/briefing?run=latest&format=whatsapp
GET /maps?variable=wave_height&time=14:00&run=latest
GET /maps/inspect?variable=wave_height&time=14:00&run=latest&lat=...&lon=...
GET /locations/weather?latitude=...&longitude=...&run=latest
GET /routes/{route_id}/media?run=latest
POST /question
POST /routes/{route_id}/question
```

Future calls:

```text
GET /regions/{region_id}/evidence
GET /routes/{route_id}/changes?since=...
```

The web app should display the same operational pair that captains understand:

```text
decision + map evidence
```

The public `predsea.com` demo currently uses that pattern:

- the map panel can load generated route media or regional Leaflet overlays
  from the API
- the chat panel calls `POST /routes/palma_ibiza/question`
- the three suggested questions plus one optional custom question use the live
  API response
- the opening chat bubble is static website copy, but every captain question is
  answered by the deployed API

If the API answer style changes in `humanintheloop/decision_engine.py`, the
demo chat reflects it after Cloud Run is deployed. A website redeploy is only
needed when changing the web copy, suggested questions, limits, or map display.

## Operational Tone

PredSea should sound like a maritime operations desk:

- calm
- concise
- route-aware
- honest about uncertainty
- focused on timing and decisions

Avoid:

- hype
- exaggerated certainty
- generic weather summaries
- raw data dumps
- sounding like a chatbot

Current answer style rules:

- Lead with the decision.
- Then give best window, comfort, risk, why, what could change, and confidence.
- Mention vessel size naturally when it changes the recommendation.
- Keep freshness warnings visible when the latest evidence package is stale.
- Avoid repeating the same sentence across sections.

Where this lives:

```text
humanintheloop/decision_engine.py
```

Tests that protect this behavior:

```text
humanintheloop/test_socib_scripts.py
humanintheloop/test_api_app.py
```

## Current Deployment Commands

Deploy Cloud Run from the repo root:

```bash
gcloud run deploy predsea-api \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars PREDSEA_GCS_BUCKET=predsea-daily-outputs,PREDSEA_GCS_PREFIX=predictions
```

Run tests locally from `humanintheloop/`:

```bash
../.venv311/bin/python -m pytest -q
```
