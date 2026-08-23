"""Convenience wrapper for Portus observations and predictions."""

from __future__ import annotations

import portus_config
import portus_observations
import portus_predictions


def fetch_portus_bundle(
    *,
    dry_run=False,
    observation_params=None,
    model_name=None,
    model_point_limit=None,
    session=None,
):
    observations = portus_observations.fetch_portus_observations(
        params=observation_params,
        session=session,
        dry_run=dry_run,
    )
    predictions = portus_predictions.fetch_portus_predictions(
        model_name=model_name,
        model_point_limit=model_point_limit,
        session=session,
        dry_run=dry_run,
    )

    errors = {}
    errors.update(observations.get("errors", {}))
    errors.update(predictions.get("errors", {}))

    return {
        "source": "puertos_portus",
        "observations": observations.get("observations", {}),
        "observation_series": observations.get("series", {}),
        "observations_lineage": observations.get("lineage", {}),
        "predictions": predictions,
        "predictions_lineage": predictions.get("lineage", {}),
        "errors": errors,
        "available": bool(observations.get("observations") or predictions.get("model_points")),
        "raw_cache_dir": str(portus_config.RAW_CACHE_DIR),
    }

