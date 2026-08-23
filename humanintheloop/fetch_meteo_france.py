"""Météo-France AROME 1.3 km wind fetcher.

Downloads 10-meter U/V wind components and wind gusts from the
Météo-France public API (portail-api.meteofrance.fr) for the Balearic
bounding box.

Requires environment variable METEO_FRANCE_API_KEY.  When the key is
absent or the endpoint is unreachable the fetcher raises so the tier
selection in ingest_atmosphere.py can fall through to the next provider.
"""

import datetime
import os
import tempfile
from pathlib import Path

import requests

from ingest_atmosphere import BALEARIC_BBOX

AROME_API_BASE = "https://public-api.meteofrance.fr/public/arome/1.0"
AROME_WCS_COVERAGE_IDS = {
    "u10": "WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND___AROME_0.01",
    "v10": "V_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND___AROME_0.01",
    "wind_gust": "WIND_SPEED_GUST__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND___AROME_0.01",
}
AROME_RESOLUTION_KM = 1.3
TIMEOUT_SECONDS = int(os.getenv("PREDSEA_METEO_FRANCE_TIMEOUT", "120"))


def _api_key():
    key = os.environ.get("METEO_FRANCE_API_KEY")
    if not key:
        raise RuntimeError("METEO_FRANCE_API_KEY is not set")
    return key


def _forecast_time_range():
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=1)
    end = now + datetime.timedelta(hours=48)
    return start, end


def _build_wcs_url(coverage_id, bbox, time_start, time_end):
    """Build a WCS GetCoverage request URL for an AROME surface variable."""
    return (
        f"{AROME_API_BASE}/wcs/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS"
        f"?SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
        f"&COVERAGEID={coverage_id}"
        f"&FORMAT=application/wmo-grib"
        f"&SUBSET=long({bbox['west']},{bbox['east']})"
        f"&SUBSET=lat({bbox['south']},{bbox['north']})"
        f"&SUBSET=time({time_start.strftime('%Y-%m-%dT%H:%M:%SZ')},{time_end.strftime('%Y-%m-%dT%H:%M:%SZ')})"
        f"&SUBSET=height(10)"
    )


def fetch_arome_wind(output_dir=None, bbox=None, dry_run=False):
    """Download AROME 10m wind vectors for the Balearic bounding box.

    Returns a dict with ``available=True`` and ``dataset_path`` on success,
    or raises on failure so the tier selector can catch and fall back.
    """
    api_key = _api_key()
    bbox = bbox or BALEARIC_BBOX
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="predsea_arome_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    time_start, time_end = _forecast_time_range()

    if dry_run:
        return {
            "available": True,
            "source": "meteo_france_arome",
            "resolution_km": AROME_RESOLUTION_KM,
            "dataset_path": str(output_dir / "arome_wind.grib2"),
            "dry_run": True,
        }

    headers = {"apikey": api_key, "Accept": "application/wmo-grib"}
    downloaded_paths = []

    for var_name, coverage_id in AROME_WCS_COVERAGE_IDS.items():
        url = _build_wcs_url(coverage_id, bbox, time_start, time_end)
        response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()

        if b"ExceptionReport" in response.content[:500]:
            raise RuntimeError(
                f"Météo-France returned an exception for {var_name}: "
                f"{response.content[:300].decode('utf-8', 'replace')}"
            )

        var_path = output_dir / f"arome_{var_name}.grib2"
        var_path.write_bytes(response.content)
        downloaded_paths.append(str(var_path))

    merged_path = output_dir / "arome_wind.grib2"
    _merge_grib_files(downloaded_paths, merged_path)

    return {
        "available": True,
        "source": "meteo_france_arome",
        "resolution_km": AROME_RESOLUTION_KM,
        "dataset_path": str(merged_path),
        "variables": list(AROME_WCS_COVERAGE_IDS.keys()),
        "time_range": {
            "start": time_start.isoformat(),
            "end": time_end.isoformat(),
        },
    }


def _merge_grib_files(paths, output_path):
    """Concatenate GRIB2 files into a single file."""
    with open(output_path, "wb") as out:
        for path in paths:
            out.write(Path(path).read_bytes())


def make_fetcher(output_dir=None, dry_run=False):
    """Return a fetcher function compatible with ingest_atmosphere.select_wind_forecast."""

    def fetcher(provider):
        if provider["id"] != "meteo_france_arome":
            raise RuntimeError(f"Wrong provider: {provider['id']}")
        return fetch_arome_wind(output_dir=output_dir, dry_run=dry_run)

    return fetcher
