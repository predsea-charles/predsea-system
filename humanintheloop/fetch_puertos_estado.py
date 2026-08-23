"""Puertos del Estado wave and observation fetcher.

This module keeps the historical public API used by the rest of PredSea
while delegating observation ingestion to the official THREDDS/OPeNDAP
connector under ``predsea.connectors.puertos_del_estado``.
"""

import datetime
import os
import re
from pathlib import Path

import requests
import xarray as xr

from predsea.connectors.puertos_del_estado.etl import fetch_puertos_observations

TIMEOUT_SECONDS = int(os.getenv("PREDSEA_PUERTOS_TIMEOUT", "60"))

# THREDDS OPeNDAP base URLs
THREDDS_BASE = "http://opendap.puertos.es/thredds"
THREDDS_CATALOG = f"{THREDDS_BASE}/catalog"
THREDDS_OPENDAP = f"{THREDDS_BASE}/dodsC"

# Balearic wave forecast catalog
WAVE_REGIONAL_BAL = "wave_regional_bal"

# Tide gauge stations relevant to Balearic routes
TIDE_GAUGE_STATIONS = {
    "mahon": {
        "catalog_id": "tidegauge_maho",
        "name": "Mahón (Menorca)",
        "latitude": 39.89,
        "longitude": 4.27,
        "relevance": "Menorca Channel, Alcudia-Ciutadella route",
    },
    "ibiza": {
        "catalog_id": "tidegauge_ibi2",
        "name": "Ibiza",
        "latitude": 38.91,
        "longitude": 1.45,
        "relevance": "Ibiza port, Palma-Ibiza and Ibiza-Formentera routes",
    },
    "alcudia": {
        "catalog_id": "tidegauge_alcu",
        "name": "Alcudia",
        "latitude": 39.84,
        "longitude": 3.13,
        "relevance": "Alcudia port, Alcudia-Ciutadella departure",
    },
    "mallorca": {
        "catalog_id": "tidegauge_mall",
        "name": "Palma de Mallorca",
        "latitude": 39.56,
        "longitude": 2.63,
        "relevance": "Palma port, departure for Palma-Ibiza and Palma-Cabrera",
    },
    "formentera": {
        "catalog_id": "tidegauge_form",
        "name": "Formentera",
        "latitude": 38.73,
        "longitude": 1.42,
        "relevance": "Formentera arrival, Ibiza-Formentera route",
    },
}


def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def _discover_latest_wave_forecast(year=None, month=None):
    """Discover the latest available Balearic wave forecast from the THREDDS catalog."""
    now = _now_utc()
    year = year or now.year
    month = month or now.month
    catalog_url = f"{THREDDS_CATALOG}/{WAVE_REGIONAL_BAL}/{year}/{month:02d}/catalog.html"

    response = requests.get(catalog_url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    # Find all forecast files (FC pattern) — sorted by date
    fc_pattern = re.compile(
        r'dataset=' + WAVE_REGIONAL_BAL + r'/\d{4}/\d{2}/(HW-\d{10}-\d{10}-B\d{10}-FC\.nc)'
    )
    matches = fc_pattern.findall(response.text)
    if not matches:
        raise RuntimeError(f"No wave forecast files found in {catalog_url}")

    latest_file = matches[-1]
    return f"{THREDDS_OPENDAP}/{WAVE_REGIONAL_BAL}/{year}/{month:02d}/{latest_file}"


def _discover_latest_hindcast(year=None, month=None):
    """Discover the latest available Balearic wave hindcast."""
    now = _now_utc()
    year = year or now.year
    month = month or now.month
    catalog_url = f"{THREDDS_CATALOG}/{WAVE_REGIONAL_BAL}/{year}/{month:02d}/catalog.html"

    response = requests.get(catalog_url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    hc_pattern = re.compile(
        r'dataset=' + WAVE_REGIONAL_BAL + r'/\d{4}/\d{2}/(HW-\d{8}-HC\.nc)'
    )
    matches = hc_pattern.findall(response.text)
    if not matches:
        return None

    latest_file = matches[-1]
    return f"{THREDDS_OPENDAP}/{WAVE_REGIONAL_BAL}/{year}/{month:02d}/{latest_file}"


def fetch_balearic_wave_forecast(dry_run=False):
    """Fetch the latest Balearic wave forecast via OPeNDAP.

    Returns a dict with wave forecast metadata and the xarray Dataset.
    """
    if dry_run:
        return {
            "available": True,
            "source": "puertos_del_estado_wave",
            "type": "wave_forecast",
            "dry_run": True,
        }

    opendap_url = _discover_latest_wave_forecast()
    print(f"  Fetching: {opendap_url}", flush=True)

    ds = xr.open_dataset(opendap_url)

    lat_range = (float(ds.latitude.min()), float(ds.latitude.max()))
    lon_range = (float(ds.longitude.min()), float(ds.longitude.max()))
    time_range = (str(ds.time.values[0])[:19], str(ds.time.values[-1])[:19])

    return {
        "available": True,
        "source": "puertos_del_estado_wave",
        "type": "wave_forecast",
        "opendap_url": opendap_url,
        "dataset": ds,
        "variables": list(ds.data_vars),
        "grid_shape": {
            "time": len(ds.time),
            "latitude": len(ds.latitude),
            "longitude": len(ds.longitude),
        },
        "lat_range": lat_range,
        "lon_range": lon_range,
        "time_range": time_range,
    }


def sample_wave_at_point(ds, latitude, longitude, variable="VHM0"):
    """Sample a wave variable at a specific lat/lon point from the dataset."""
    point = ds[variable].sel(
        latitude=latitude,
        longitude=longitude,
        method="nearest",
    )
    return {
        "variable": variable,
        "values": [round(float(v), 2) for v in point.values if v == v],
        "times": [str(t)[:19] for t in ds.time.values],
        "sampled_lat": float(point.latitude),
        "sampled_lon": float(point.longitude),
    }


def fetch_balearic_observations(dry_run=False):
    """Fetch observations from all discoverable Puertos del Estado stations."""
    cache_dir = Path(os.getenv("PREDSEA_PUERTOS_CACHE_DIR", "mvp_data/puertos_del_estado"))
    result = fetch_puertos_observations(dry_run=dry_run, cache_dir=cache_dir)
    return {
        "observations": result.get("observations", {}),
        "measurements": result.get("measurements", {}),
        "errors": result.get("errors", {}),
        "lineage": result.get("lineage", {}),
        "source": result.get("source", "puertos_del_estado"),
        "network_ids": ["THREDDS", "OPeNDAP"],
        "catalog_count": result.get("catalog_count", 0),
        "catalog_stations": result.get("catalog_stations", []),
    }


def lineage_for_puertos_observations(result):
    """Generate data lineage for Puertos del Estado observations."""
    obs = result.get("observations", {})
    matched = [key for key, value in obs.items() if isinstance(value, dict)]
    return {
        "source": "puertos_del_estado",
        "status": "matched_successfully" if matched else "unavailable",
        "stations_matched": len(matched),
        "station_ids": matched,
    }
