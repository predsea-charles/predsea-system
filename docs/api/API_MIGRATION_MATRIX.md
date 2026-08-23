# PredSea API Migration Matrix

This migration matrix tracks every legacy/static API call in the old or web-demo frontend and maps it to the corresponding live, production-ready PredSea endpoint.

---

| Legacy Frontend File | Legacy Method/Variable | Old Endpoint / Mock Path | New LIVE Endpoint | Migration Status | Required Transformation & Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `web/app.js` | `loadJson(path)` | `./data/ocean_conditions.json` | `GET /places/{place_id}/weather` | `RESPONSE_MAPPING_REQUIRED` | Replace static local file reads with direct requests to the live place weather endpoint for specific port slices. |
| `web/app.js` | `renderCurrentVectors`| `./data/ocean_conditions.json` (current_points) | `GET /routes/{route_id}/evidence` | `RESPONSE_MAPPING_REQUIRED` | Extract current vectors (`speed_kn`, `direction_deg`) along the route waypoints timeline. |
| `web/app.js` | `renderWaveField` | `./data/ocean_conditions.json` (wave_points) | `GET /routes/{route_id}/evidence` | `RESPONSE_MAPPING_REQUIRED` | Extract wave timeline fields (`wave_heights`) at each sampling point step. |
| `web/app.js` | `renderChat` | Mocked chat array | `POST /routes/{route_id}/question` | `METHOD_CHANGE` | Convert static mock conversations into dynamic calls using route passage weather evidence. |
| `web/app.js` | `statusPill` | Mocked rules based on mean waves | `GET /routes/{route_id}/briefing` | `RESPONSE_MAPPING_REQUIRED` | Bind directly to the `feasibility` and `feasibility_rating` fields returned by the live briefing. |
