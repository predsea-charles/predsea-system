# Distance Fallback Graph Design

## Goal

Keep PredSea’s current fixed place-pair distance table as the primary source for
known planning distances, but add a graph-based sea-route fallback for place
pairs that are not in the curated table.

This preserves the stable values we already trust for major route pairs while
expanding coverage to additional locations without inventing straight-line
distances over land.

## Background

PredSea now exposes:

- a fixed place distance endpoint: `/places/distance`
- weighted maritime route results from the route engine

The fixed table is the right answer for curated planning pairs such as Palma ->
Ibiza. The missing piece is a fallback for uncatalogued place pairs so the API
can still return a useful navigable sea distance instead of a straight-line
proxy.

## Core Principle

Use the fixed table first.

If a pair is not present there, compute a navigable sea route distance with a
graph-based fallback.

The API contract should remain stable:

- same endpoint
- same response fields
- same user-facing meaning

The implementation detail changes underneath.

## Scope

### In Scope

- Keep the curated place distance table as the first lookup.
- Add a graph-based fallback for uncatalogued place pairs.
- Reuse the same `/places/distance` endpoint for both paths.
- Reuse the same internal helper for route-question passage evidence so route
  answers and distance answers stay consistent.
- Preserve the weighted route engine as a separate weather/current-aware route
  layer.

### Out of Scope

- Replacing the fixed table with the graph engine.
- Changing route-question wording.
- Changing weighted route precompute behavior.
- Introducing a new public distance endpoint.

## Proposed Behavior

### Fixed Table First

For a place pair like `palma -> ibiza`, PredSea should:

1. look in the fixed place distance table
2. return that curated distance and travel-time estimate if present

This remains the default because it is stable and explainable.

### Graph Fallback

If the pair is not in the fixed table:

1. resolve the origin and destination places
2. compute a navigable sea route distance using the graph-based route
   strategy
3. return that computed nautical distance and a derived typical travel time

The fallback should be used only when the curated table does not cover the
pair.

### Same Endpoint, Same Shape

The `/places/distance` endpoint should keep returning:

- `origin_place_id`
- `origin_place_name`
- `destination_place_id`
- `destination_place_name`
- `distance_nm`
- `estimated_time_h`
- `source_tag`
- `computed_at_utc`

The caller should not need to know which path produced the answer.

## Internal Design

### Distance Resolver

Introduce a small resolver layer that:

1. checks the fixed table
2. if missing, asks the graph-based route engine for a sea-route distance
3. returns a unified metrics object

That resolver should be the single place where distance and travel-time
selection logic lives.

### Source Tagging

Keep a source tag internally so we can tell which path was used in logs and
tests.

Suggested tags:

- `place_distance_table_v1` for the fixed table
- `graph_sea_route_v1` for the fallback route engine

The user-facing API response can remain compact, but the source tag should still
be returned so the provenance is visible.

### Route Question Consistency

Route question evidence should use the same distance resolver so that:

- route answers and distance answers agree
- fixed pairs remain stable
- uncatalogued pairs get a navigable fallback distance instead of a straight
  line

## Graph Fallback Strategy

The graph fallback should use a maritime sea-route strategy rather than a simple
geodesic.

The fallback must:

- avoid land-crossing shortcuts
- prefer navigable sea paths
- remain deterministic for the same inputs

If the graph library cannot produce a route for a pair, the endpoint may fall
back to the fixed table only if the pair exists there. If neither path can
produce a result, the endpoint should fail clearly rather than guess.

## Error Handling

- Unknown places should still return a clear unsupported-place error.
- Fixed-table lookup failures should not break the request if the graph fallback
  can answer it.
- Graph fallback failures should be visible in logs and should not silently
  produce a straight-line proxy.
- If neither the fixed table nor the graph can answer a pair, return a clear
  404 or not-found style error.

## Testing

Add tests for:

- fixed-table pairs still returning the curated distance
- uncatalogued pairs using the graph fallback
- route-question evidence using the same resolver as `/places/distance`
- source tags distinguishing fixed-table and graph-fallback results
- failure behavior when neither source can resolve a pair

## Implementation Notes

- Keep the fixed distance table small, stable, and human-readable.
- Keep the graph fallback isolated so we can replace its implementation later
  without changing the API contract.
- Do not change the weighted route engine; this feature only changes how
  planning distance is resolved.

## Success Criteria

After implementation:

- Palma -> Ibiza should still return the curated fixed distance.
- Uncatalogued place pairs should return a navigable sea distance when the
  graph fallback can solve them.
- Route questions and distance queries should agree on the distance basis.
- The API contract should remain unchanged for callers.

