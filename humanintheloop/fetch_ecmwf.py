"""ECMWF Open Data IFS wind fetcher.

Downloads 10-meter U/V wind components from the ECMWF open data
service using the ``ecmwf-opendata`` Python client, then subsets
to the Balearic bounding box.

No API key is required for ECMWF open data.  The current open subset
serves 0.25-degree (~25 km) resolution; native 9 km open data is
expected later in 2026.  This fetcher downloads whatever resolution
ECMWF publishes and subsets it to the Balearic region.

When the service is unreachable the fetcher raises so
ingest_atmosphere.py can record an all-providers-unavailable lineage.
"""

import datetime
import os
import tempfile
from pathlib import Path

from ingest_atmosphere import WESTMED_BBOX

ECMWF_RESOLUTION_KM = 9.0
TIMEOUT_SECONDS = int(os.getenv("PREDSEA_ECMWF_TIMEOUT", "120"))


def _latest_run_time():
    """Estimate the latest available ECMWF run (00, 06, 12, 18 UTC).

    ECMWF open data is typically available ~5h after the run start.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    available_hour = now.hour - 5
    if available_hour >= 18:
        return 18
    elif available_hour >= 12:
        return 12
    elif available_hour >= 6:
        return 6
    return 0


def _forecast_steps():
    """Return the forecast lead-time steps to download (hours)."""
    return list(range(0, 49, 3))


def _subset_to_bbox(global_path, subset_path, bbox):
    """Subset a global GRIB2 file to the Balearic bounding box using cfgrib+xarray."""
    import cfgrib
    import xarray as xr

    datasets = cfgrib.open_datasets(str(global_path))
    subsetted = []
    for ds in datasets:
        if "latitude" in ds.coords and "longitude" in ds.coords:
            # Handle longitude: ECMWF may use 0-360 or -180-180
            lons = ds.longitude.values
            if lons.max() > 180:
                # Convert bbox west/east to 0-360
                west = bbox["west"] % 360
                east = bbox["east"] % 360
            else:
                west = bbox["west"]
                east = bbox["east"]

            sub = ds.sel(
                latitude=slice(bbox["north"], bbox["south"]),
                longitude=slice(west, east),
            )
            subsetted.append(sub)
        else:
            subsetted.append(ds)

    if subsetted:
        merged = xr.merge(subsetted)
        merged.to_netcdf(str(subset_path))
        for ds in datasets:
            ds.close()
        return subset_path

    raise RuntimeError("No datasets with latitude/longitude found in GRIB2 file")


def fetch_ecmwf_wind(output_dir=None, bbox=None, dry_run=False):
    """Download IFS 10m wind vectors from ECMWF open data.

    Downloads the global file, then subsets to the Balearic bbox.
    Returns a dict with ``available=True`` and ``dataset_path`` on success,
    or raises on failure.
    """
    bbox = bbox or WESTMED_BBOX
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="predsea_ecmwf_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = output_dir / "ecmwf_wind.nc"
    run_time = _latest_run_time()

    if dry_run:
        return {
            "available": True,
            "source": "ecmwf_open_data",
            "resolution_km": ECMWF_RESOLUTION_KM,
            "dataset_path": str(dataset_path),
            "dry_run": True,
        }

    from ecmwf.opendata import Client

    client = Client(source="ecmwf")

    # Download global GRIB2 first (area post-processing not supported)
    global_path = output_dir / "ecmwf_wind_global.grib2"
    client.retrieve(
        type="fc",
        stream="oper",
        param=["10u", "10v"],
        time=run_time,
        step=_forecast_steps(),
        target=str(global_path),
    )

    if not global_path.exists() or global_path.stat().st_size == 0:
        raise RuntimeError("ECMWF download produced an empty file")

    # Subset to Balearic bbox and save as NetCDF
    _subset_to_bbox(global_path, dataset_path, bbox)

    # Compute effective resolution from the subsetted grid
    effective_resolution_km = _compute_grid_resolution(dataset_path)

    # Clean up global file
    global_path.unlink(missing_ok=True)

    return {
        "available": True,
        "source": "ecmwf_open_data",
        "resolution_km": effective_resolution_km or ECMWF_RESOLUTION_KM,
        "dataset_path": str(dataset_path),
        "model_run": f"{run_time:02d}Z",
        "variables": ["10u", "10v"],
        "steps": _forecast_steps(),
    }


def _compute_grid_resolution(dataset_path):
    """Compute the grid resolution in km from the subsetted file."""
    try:
        import xarray as xr
        ds = xr.open_dataset(str(dataset_path))
        if "latitude" in ds.coords and len(ds.latitude) > 1:
            lat_step = abs(float(ds.latitude[1] - ds.latitude[0]))
            # 1 degree latitude ~ 111 km
            resolution_km = round(lat_step * 111, 1)
            ds.close()
            return resolution_km
        ds.close()
    except Exception:
        pass
    return None


def make_fetcher(output_dir=None, dry_run=False):
    """Return a fetcher function compatible with ingest_atmosphere.select_wind_forecast."""

    def fetcher(provider):
        if provider["id"] != "ecmwf_open_data":
            raise RuntimeError(f"Wrong provider: {provider['id']}")
        return fetch_ecmwf_wind(output_dir=output_dir, dry_run=dry_run)

    return fetcher
