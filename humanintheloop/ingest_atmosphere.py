"""Atmospheric provider tier selection with real fetcher integration.

Defines the tiered atmospheric provider hierarchy for the expanded
Mediterranean routing box:

  Tier 1: Météo-France AROME (1.3 km)
  Tier 2: AEMET HARMONIE-AROME (2.5 km)
  Tier 3: ECMWF Open Data IFS (9 km)

This module is the entry point for atmospheric wind data.  The
``select_wind_forecast`` function iterates providers in priority order,
calling each fetcher and returning the first successful result.

Phase 2 adds ``build_fetchers()`` which constructs real fetcher
callables from the fetch_meteo_france, fetch_aemet, and fetch_ecmwf
modules, gated by whether the required API credentials are configured.
"""

import os

BALEARIC_BBOX = {
    "south": 38.0,
    "north": 41.5,
    "west": 0.5,
    "east": 4.5,
}

WESTMED_BBOX = {
    "south": 35.0,
    "north": 44.5,
    "west": -1.0,
    "east": 16.5,
}


ATMOSPHERIC_PROVIDERS = [
    {
        "id": "meteo_france_arome",
        "label": "Meteo-France AROME 0.01 degree",
        "tier": 1,
        "resolution_km": 1.3,
        "variables": ["u10", "v10", "wind_gust"],
    },
    {
        "id": "aemet_harmonie_arome",
        "label": "AEMET HARMONIE-AROME",
        "tier": 2,
        "resolution_km": 2.5,
        "variables": ["u10", "v10", "wind_gust"],
    },
    {
        "id": "ecmwf_open_data",
        "label": "ECMWF Open Data",
        "tier": 3,
        "resolution_km": 9.0,
        "variables": ["u10", "v10", "wind_gust"],
    },
]


def select_wind_forecast(fetchers, bbox=BALEARIC_BBOX):
    errors = {}
    for provider in ATMOSPHERIC_PROVIDERS:
        fetcher = fetchers.get(provider["id"])
        if fetcher is None:
            errors[provider["id"]] = "fetcher not configured"
            continue
        try:
            result = fetcher(provider)
        except Exception as error:
            errors[provider["id"]] = str(error)
            continue
        if result.get("available"):
            return normalize_wind_result(result, provider, bbox, errors)
        errors[provider["id"]] = result.get("error", "provider unavailable")

    return {
        "available": False,
        "source": None,
        "resolution_km": None,
        "tier": None,
        "bbox": dict(bbox),
        "errors": errors,
    }


def normalize_wind_result(result, provider, bbox, errors=None):
    normalized = dict(result)
    normalized.update(
        {
            "available": True,
            "source": provider["id"],
            "label": provider["label"],
            "tier": provider["tier"],
            "resolution_km": provider["resolution_km"],
            "bbox": dict(bbox),
            "variables": list(provider["variables"]),
        }
    )
    if errors:
        normalized["fallback_errors"] = errors
    return normalized


def lineage_for_wind_result(result):
    if not result.get("available"):
        return {
            "source": None,
            "resolution_km": None,
            "status": "unavailable",
            "tier": None,
        }
    return {
        "source": result.get("source"),
        "resolution_km": result.get("resolution_km"),
        "status": "active",
        "tier": result.get("tier"),
    }


def build_fetchers(output_dir=None, dry_run=False):
    """Construct real fetcher callables from available credentials.

    Returns a dict of ``{provider_id: fetcher_callable}`` for every
    provider whose API credentials are configured.  Providers without
    credentials are silently skipped, so the tier selector will log
    ``fetcher not configured`` for them and fall through.
    """
    from pathlib import Path

    resolved_dir = str(Path(output_dir)) if output_dir else None
    fetchers = {}

    # Tier 1: Météo-France AROME
    if os.environ.get("METEO_FRANCE_API_KEY"):
        import fetch_meteo_france
        fetchers["meteo_france_arome"] = fetch_meteo_france.make_fetcher(
            output_dir=resolved_dir, dry_run=dry_run,
        )

    # Tier 2: AEMET HARMONIE-AROME
    if os.environ.get("AEMET_API_KEY"):
        import fetch_aemet
        fetchers["aemet_harmonie_arome"] = fetch_aemet.make_fetcher(
            output_dir=resolved_dir, dry_run=dry_run,
        )

    # Tier 3: ECMWF Open Data (no API key required)
    fetchers["ecmwf_open_data"] = _make_ecmwf_fetcher(resolved_dir, dry_run)

    return fetchers


def _make_ecmwf_fetcher(output_dir=None, dry_run=False):
    """Lazily import and return the ECMWF fetcher."""
    import fetch_ecmwf
    return fetch_ecmwf.make_fetcher(output_dir=output_dir, dry_run=dry_run)


def run_atmospheric_ingestion(output_dir=None, dry_run=False):
    """Run the full atmospheric tier selection and return the result with lineage.

    This is the main entry point for pipeline integration.
    """
    fetchers = build_fetchers(output_dir=output_dir, dry_run=dry_run)
    atmospheric_sources = []
    for provider in ATMOSPHERIC_PROVIDERS:
        fetcher = fetchers.get(provider["id"])
        if fetcher is None:
            atmospheric_sources.append({
                **provider,
                "available": False,
                "source_family": "atmosphere",
                "error": "fetcher not configured",
            })
            continue
        try:
            result = fetcher(provider)
        except Exception as error:
            atmospheric_sources.append({
                **provider,
                "available": False,
                "source_family": "atmosphere",
                "error": str(error),
            })
            continue
        atmospheric_sources.append({
            **provider,
            **result,
            "source_family": "atmosphere",
        })
    wind_result = select_wind_forecast(fetchers, bbox=WESTMED_BBOX)
    wind_lineage = lineage_for_wind_result(wind_result)

    return {
        "wind_result": wind_result,
        "wind_lineage": wind_lineage,
        "atmospheric_sources": atmospheric_sources,
        "fetchers_configured": list(fetchers.keys()),
    }
