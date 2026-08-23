"""Convenience wrapper for EMODnet Physics observations."""

from __future__ import annotations

from pathlib import Path

from predsea.connectors.emodnet_physics.etl import fetch_emodnet_observations


def fetch_emodnet_bundle(
    *,
    dry_run=False,
    timeout=60,
    max_retries=2,
    backoff_seconds=2,
    session=None,
):
    cache_dir = Path("mvp_data/emodnet_physics")
    result = fetch_emodnet_observations(
        dry_run=dry_run,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        session=session,
    )
    return {
        "source": "emodnet_physics",
        "observations": result.get("observations", {}),
        "measurements": result.get("measurements", {}),
        "stations": result.get("stations", []),
        "errors": result.get("errors", {}),
        "lineage": result.get("lineage", {}),
        "available": bool(result.get("observations")),
        "network_ids": result.get("network_ids", ["ERDDAP"]),
        "catalog_count": result.get("catalog_count", 0),
        "catalog_stations": result.get("catalog_stations", []),
        "cache_dir": str(cache_dir),
    }
