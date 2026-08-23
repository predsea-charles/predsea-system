# PredSea Route Waypoint + Checkpoint Endpoint Design

## Goal
Add a maritime route endpoint that returns minimalist route geometry plus a parallel checkpoint timeline for a route between two places, with optional raw latitude/longitude overrides on day one.

This endpoint must stay aligned with PredSea's canonical place registry and route-distance logic. It should use the `searoute` Python library to generate a navigable sea path and expose the path as ordered waypoints.
It should also derive in-route checkpoint ETAs and weather samples from the same route, while keeping berth/arrival clutter out of the geometry layer.

## User-Facing API

### Endpoint
`GET /places/route/{origin}/{destination}`

### Query parameters
- `origin_latitude` and `origin_longitude` optional
- `destination_latitude` and `destination_longitude` optional

### Resolution rules
1. If origin latitude/longitude are provided, use them.
2. Otherwise resolve `{origin}` via the canonical place registry.
3. If destination latitude/longitude are provided, use them.
4. Otherwise resolve `{destination}` via the canonical place registry.
5. If a side cannot be resolved, return a clear 422 error.

### Response shape
```json
{
  "origin_place_id": "palma",
  "origin_place_name": "Palma",
  "origin_latitude": 39.56,
  "origin_longitude": 2.63,
  "destination_place_id": "ibiza",
  "destination_place_name": "Ibiza",
  "destination_latitude": 38.91,
  "destination_longitude": 1.45,
  "distance_nm": 100.0,
  "estimated_time_h": 6.25,
  "waypoints": [
    { "lat": 39.40, "lng": 2.40 },
    { "lat": 39.10, "lng": 2.05 }
  ],
  "checkpoints": [
    {
      "waypoint_index": 0,
      "lat": 39.40,
      "lng": 2.40,
      "eta_utc": "2026-06-17T13:30:00Z",
      "distance_from_origin_nm": 28.0,
      "forecast_time_utc": "2026-06-17T13:30:00Z",
      "weather": {
        "wave_height_m": 1.1,
        "current_speed_kn": 0.5
      }
    },
    {
      "waypoint_index": 1,
      "lat": 39.10,
      "lng": 2.05,
      "eta_utc": "2026-06-17T15:20:00Z",
      "distance_from_origin_nm": 61.0,
      "forecast_time_utc": "2026-06-17T15:20:00Z",
      "weather": {
        "wave_height_m": 1.3,
        "current_speed_kn": 0.4
      }
    }
  ],
  "source_tag": "graph_sea_route_v1",
  "computed_at_utc": "2026-06-17 12:00 UTC"
}
```

## Implementation Approach

### Shared resolver
Add a small shared route resolver in the API layer that:
- resolves place IDs through the canonical place registry
- accepts coordinate overrides when provided
- normalizes both inputs into a single origin/destination point structure

### Geometry engine
Use `searoute` to compute the route geometry and nautical distance.
- The output should be converted into a simple list of `{lat, lng}` waypoints.
- The distance should be returned in nautical miles.
- Estimated travel time should be derived from the route length and a default planning speed, unless the library provides a reliable duration directly.

### Checkpoint engine
Derive a second array of in-route checkpoints from the geometry:
- keep the geometry minimalist
- keep the first and last navigable sea waypoints only if they are meaningful sea points, not berth/arrival clutter
- compute cumulative distance from origin to each checkpoint
- compute `eta_utc` from the route departure context and the route distance at a default planning speed
- sample weather at each checkpoint ETA using the existing PredSea forecast/weather lookup path
- store the sampled weather separately from the geometry so the route shape remains clean

### Fallback behavior
- If the route library cannot produce a valid maritime path, return a clear error rather than inventing a straight line.
- If only place resolution succeeds and no coordinates are available, still fail gracefully with a 422.
- If the geometry library raises on a malformed route, surface a controlled API error and keep the existing distance endpoints unchanged.

## Non-Goals
- Do not replace the existing `/places/distance` contract.
- Do not change the weighted optimal route solver.
- Do not invent waypoints when the sea routing library cannot produce them.
- Do not force berth or arrival waypoints into the geometry layer.
- Do not invent weather values when a checkpoint sample is unavailable.

## Testing
Add tests that cover:
- place ID only resolution
- raw coordinate overrides on day one
- mixed place/coordinate requests
- missing resolution inputs returning 422
- route geometry returning a waypoint list
- checkpoint timeline derived from the geometry
- checkpoint weather sampling at waypoint ETA
- route geometry failure returning a controlled error

## Docs
Update the API README and the WhatsApp/API usage docs so the route waypoint endpoint is visible alongside:
- `/places/distance`
- `/places/distance/coordinates`
- `/routes/optimal/{origin}/{destination}`
