import datetime
import os
import time
from pathlib import Path

import pandas as pd


WMOP_SURFACE_URL = (
    "https://thredds.socib.es/thredds/dodsC/"
    "operational_models/oceanographical/hydrodynamics/model_run_aggregation/"
    "wmop_surface/wmop_surface_best.ncd"
)
SAPO_IB_URL = (
    "https://thredds.socib.es/thredds/dodsC/"
    "operational_models/oceanographical/wave/model_run_aggregation/"
    "sapo_ib/sapo_ib_best.ncd"
)

LON_MIN, LON_MAX = 1.0, 4.5
LAT_MIN, LAT_MAX = 38.5, 40.5
THREDDS_ATTEMPTS = int(os.getenv("PREDSEA_SOCIB_THREDDS_ATTEMPTS", "3"))
THREDDS_RETRY_DELAY_SECONDS = int(os.getenv("PREDSEA_SOCIB_THREDDS_RETRY_DELAY_SECONDS", "20"))


def get_balearic_forecast(output_dir="./mvp_data/socib_thredds", dry_run=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    waves_path = output_dir / "balearic_waves.nc"
    currents_path = output_dir / "balearic_currents.nc"
    if dry_run:
        return {
            "waves_path": waves_path,
            "currents_path": currents_path,
            "metadata": source_metadata(),
        }

    with_retries("SOCIB SAPO-IB waves", lambda: fetch_sapo_waves(waves_path))
    with_retries("SOCIB WMOP currents", lambda: fetch_wmop_currents(currents_path))
    return {
        "waves_path": waves_path,
        "currents_path": currents_path,
        "metadata": source_metadata(),
    }


def source_metadata():
    return {
        "wave_model": "SOCIB SAPO-IB",
        "current_model": "SOCIB WMOP surface",
        "wave_url": SAPO_IB_URL,
        "current_url": WMOP_SURFACE_URL,
    }


def forecast_window():
    now = datetime.datetime.now(datetime.timezone.utc)
    return now - datetime.timedelta(hours=6), now + datetime.timedelta(days=1)


def _utc_naive_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.tz_localize(None)


def with_retries(label, operation, attempts=None, delay_seconds=None):
    attempts = attempts or THREDDS_ATTEMPTS
    delay_seconds = THREDDS_RETRY_DELAY_SECONDS if delay_seconds is None else delay_seconds
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except OSError as error:
            last_error = error
            if attempt >= attempts:
                break
            print(f"{label} failed on attempt {attempt}/{attempts}: {error}. Retrying in {delay_seconds}s.", flush=True)
            time.sleep(delay_seconds)
    raise last_error


def fetch_sapo_waves(output_path):
    import xarray as xr

    start_time, end_time = forecast_window()
    start_time = _utc_naive_timestamp(start_time)
    end_time = _utc_naive_timestamp(end_time)
    with xr.open_dataset(SAPO_IB_URL) as dataset:
        time_name = "time2" if "time2" in dataset.coords else "time"
        subset = dataset[[
            "significant_wave_height",
            "average_wave_direction",
            "wave_height_of_swell_part",
        ]].sel(
            longitude=slice(LON_MIN, LON_MAX),
            latitude=slice(LAT_MIN, LAT_MAX),
            **{time_name: slice(start_time, end_time)},
        )
        subset = subset.drop_vars(
            [
                name for name in (
                    "time",
                    "time1",
                    "time_run",
                    "time1_run",
                    "time2_run",
                    "time_offset",
                    "time1_offset",
                    "time2_offset",
                )
                if name in subset and name != time_name
            ],
            errors="ignore",
        )
        normalized = subset.rename(
            {
                time_name: "time",
                "significant_wave_height": "VHM0",
                "average_wave_direction": "VMDR",
                "wave_height_of_swell_part": "VHM0_SW1",
            }
        )
        normalized["VHM0"].attrs.update(units="m", long_name="significant wave height")
        normalized["VMDR"].attrs.update(units="degree", long_name="mean wave direction")
        normalized["VHM0_SW1"].attrs.update(units="m", long_name="primary swell significant wave height")
        normalized.encoding = {}
        normalized.to_netcdf(output_path)
        normalized.close()


def fetch_wmop_currents(output_path):
    import xarray as xr

    start_time, end_time = forecast_window()
    start_time = _utc_naive_timestamp(start_time)
    end_time = _utc_naive_timestamp(end_time)
    with xr.open_dataset(WMOP_SURFACE_URL) as dataset:
        subset = dataset[["u", "v"]].sel(
            lon_uv=slice(LON_MIN, LON_MAX),
            lat_uv=slice(LAT_MIN, LAT_MAX),
            time=slice(start_time, end_time),
        )
        subset = subset.drop_vars(["ocean_time", "time_run", "time_offset"], errors="ignore")
        normalized = subset.rename(
            {
                "lon_uv": "longitude",
                "lat_uv": "latitude",
                "u": "uo",
                "v": "vo",
            }
        )
        normalized["uo"].attrs.update(units="m s-1", long_name="eastward sea surface velocity")
        normalized["vo"].attrs.update(units="m s-1", long_name="northward sea surface velocity")
        normalized.encoding = {}
        normalized.to_netcdf(output_path)
        normalized.close()


if __name__ == "__main__":
    result = get_balearic_forecast()
    print(f"SOCIB THREDDS files downloaded to {Path(result['waves_path']).parent}/")
