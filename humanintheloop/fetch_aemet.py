"""AEMET HARMONIE-AROME 2.5 km wind fetcher.

Downloads 10-meter wind forecast data from AEMET OpenData API
(opendata.aemet.es) for the Balearic bounding box.

Requires environment variable AEMET_API_KEY (free registration at
https://opendata.aemet.es/centrodedescargas/altaUsuario).

When the key is absent or the endpoint is unreachable, the fetcher
raises so ingest_atmosphere.py can fall through to ECMWF.
"""

import datetime
import os
import tempfile
from pathlib import Path

import requests

from ingest_atmosphere import BALEARIC_BBOX

AEMET_API_BASE = "https://opendata.aemet.es/opendata/api"
HARMONIE_RESOLUTION_KM = 2.5
TIMEOUT_SECONDS = int(os.getenv("PREDSEA_AEMET_TIMEOUT", "120"))

# AEMET HARMONIE-AROME endpoints for wind surface data
# The API uses a two-step pattern: first request returns a URL to the actual data
HARMONIE_AREA_MAP = {
    "peninsula_baleares": "pen",
    "canarias": "can",
}


def _api_key():
    key = os.environ.get("AEMET_API_KEY")
    if not key:
        raise RuntimeError("AEMET_API_KEY is not set")
    return key


def _forecast_run():
    """Determine the latest available model run (00, 06, 12, 18 UTC)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    # HARMONIE runs are typically available ~3h after init time
    available_hour = now.hour - 3
    if available_hour >= 18:
        return "18"
    elif available_hour >= 12:
        return "12"
    elif available_hour >= 6:
        return "06"
    return "00"


def _request_harmonie_data(api_key, area="pen", run_hour=None):
    """Request HARMONIE-AROME surface forecast from AEMET.

    AEMET's two-step API: first call returns a JSON with a ``datos`` URL
    pointing to the actual binary file.
    """
    run_hour = run_hour or _forecast_run()
    url = (
        f"{AEMET_API_BASE}/prediccion/especifica/municipio/horaria"
        f"/harmonie/sup/{area}/{run_hour}"
    )
    headers = {"api_key": api_key, "Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    metadata = response.json()

    if metadata.get("estado") != 200:
        raise RuntimeError(
            f"AEMET returned status {metadata.get('estado')}: "
            f"{metadata.get('descripcion', 'unknown error')}"
        )

    data_url = metadata.get("datos")
    if not data_url:
        raise RuntimeError("AEMET response missing 'datos' download URL")

    return data_url


def _download_data(data_url, output_path, api_key):
    """Download the actual forecast data from the AEMET datos URL."""
    headers = {"api_key": api_key}
    response = requests.get(data_url, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    Path(output_path).write_bytes(response.content)
    return output_path


def fetch_harmonie_wind(output_dir=None, bbox=None, dry_run=False):
    """Download HARMONIE-AROME 10m wind for the Balearic bounding box.

    Returns a dict with ``available=True`` and ``dataset_path`` on success,
    or raises on failure.
    """
    api_key = _api_key()
    bbox = bbox or BALEARIC_BBOX
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="predsea_aemet_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    run_hour = _forecast_run()

    if dry_run:
        return {
            "available": True,
            "source": "aemet_harmonie_arome",
            "resolution_km": HARMONIE_RESOLUTION_KM,
            "dataset_path": str(output_dir / "harmonie_wind.grib2"),
            "dry_run": True,
        }

    data_url = _request_harmonie_data(api_key, area="pen", run_hour=run_hour)
    dataset_path = output_dir / "harmonie_wind.grib2"
    _download_data(data_url, dataset_path, api_key)

    return {
        "available": True,
        "source": "aemet_harmonie_arome",
        "resolution_km": HARMONIE_RESOLUTION_KM,
        "dataset_path": str(dataset_path),
        "model_run": run_hour,
        "variables": ["u10", "v10", "wind_gust"],
    }


def make_fetcher(output_dir=None, dry_run=False):
    """Return a fetcher function compatible with ingest_atmosphere.select_wind_forecast."""

    def fetcher(provider):
        if provider["id"] != "aemet_harmonie_arome":
            raise RuntimeError(f"Wrong provider: {provider['id']}")
        return fetch_harmonie_wind(output_dir=output_dir, dry_run=dry_run)

    return fetcher
