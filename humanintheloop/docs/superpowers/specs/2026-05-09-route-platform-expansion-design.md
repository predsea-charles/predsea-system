# Route Platform Expansion Design

## Goal

Expand the PredSea MVP from one hard-coded Palma-Ibiza briefing into a route-aware platform that can generate artifacts for multiple Balearic routes and adjust advice by vessel size.

## Routes

Create `routes.json` as the route catalog. Each route has a stable route ID, display name, origin, destination, approximate port coordinates, and offshore sample points used by `route_analysis.py` when reading forecast files.

Initial routes:

- `palma_ibiza`: Palma to Ibiza
- `palma_barcelona`: Palma to Barcelona
- `palma_cabrera`: Palma to Cabrera
- `palma_valencia`: Palma to Valencia
- `ibiza_formentera`: Ibiza to Formentera
- `alcudia_ciutadella`: Alcudia to Ciutadella

The sample points are MVP navigation-analysis points, not a navigation chart. They are used to sample the forecast along exposed water rather than averaging a geographic box.

## CLI Behavior

`briefing.py` accepts:

- `--route <route_id>`, defaulting to `palma_ibiza`
- `--vessel-class small|medium|large`, defaulting to `medium`
- existing `--question`, `--location-label`, and `--current-time`
- `--list-routes` to print available route IDs and labels

Artifacts are written under `mvp_data/routes/<route_id>/`.

## Vessel Class

Advice changes by vessel class:

- `small`: vessels under 15m, conservative thresholding
- `medium`: vessels 15-24m, default thresholding
- `large`: vessels over 24m, more tolerant thresholding

The recommendation still reports confidence honestly. Vessel class changes advice severity and wording, not the underlying forecast values.

## Data Flow

1. `briefing.py` loads the selected route from `routes.json`.
2. Forecast files are downloaded to the existing `mvp_data/` location.
3. `route_analysis.py` samples waves and currents at the route sample points.
4. `route_analysis.py` builds a snapshot containing route metadata, forecast, observations, vessel class, and recommendation.
5. `briefing.py` writes route-specific artifacts to `mvp_data/routes/<route_id>/`.

## Testing

Unit tests should cover route catalog loading, route-aware forecast sampling, vessel-class recommendation differences, route-specific output folders, and backward-compatible artifact rendering.
