import copernicusmarine
import datetime
import json
import os
import shutil
import time
from pathlib import Path

import xarray as xr

OUTPUT_DIR = str(Path(__file__).resolve().parent / "mvp_data")
os.makedirs(OUTPUT_DIR, exist_ok=True)
REQUIRED_COPERNICUS_ENV = (
    "COPERNICUSMARINE_SERVICE_USERNAME",
    "COPERNICUSMARINE_SERVICE_PASSWORD",
)
COPERNICUS_MAX_ATTEMPTS = int(os.getenv("PREDSEA_COPERNICUS_MAX_ATTEMPTS", "3"))
COPERNICUS_BACKOFF_SECONDS = float(os.getenv("PREDSEA_COPERNICUS_BACKOFF_SECONDS", "20"))

# Current Copernicus Marine Mediterranean analysis/forecast dataset IDs.
PHY_ID = "cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m"
WAV_ID = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"
CORE_WAVE_VARIABLES = ["VHM0", "VMDR"]
WAVE_PARTITION_VARIABLES = [
    "VHM0_SW1",
    "VMDR_SW1",
    "VHM0_SW2",
    "VMDR_SW2",
    "VHM0_WW",
    "VMDR_WW",
]
WAVE_VARIABLES = [
    "VHM0",
    "VMDR",
    *WAVE_PARTITION_VARIABLES,
]

from dotenv import load_dotenv
load_dotenv()

# Map credentials from .env to copernicusmarine expected env vars
if "COPERNICUS_USERNAME" in os.environ and "COPERNICUS_PASSWORD" in os.environ:
    os.environ["COPERNICUSMARINE_SERVICE_USERNAME"] = os.environ["COPERNICUS_USERNAME"]
    os.environ["COPERNICUSMARINE_SERVICE_PASSWORD"] = os.environ["COPERNICUS_PASSWORD"]

# Coordinates for the expanded Mediterranean routing box.
# Covers the full Western Mediterranean basin: the Alboran Sea west of
# Gibraltar, Spain, the Balearics, the Gulf of Lion, France, Sardinia/Corsica,
# and the Tyrrhenian/Algerian cruising grounds including Naples/Sicily/Messina.
# This must stay wide enough to cover every region in
# simulation/marine/regions/*.json -- alboran_1km's bbox reaches
# longitude -6.0, which is why lon_min is not -1.0.
lon_min, lon_max = -6.0, 16.5
lat_min, lat_max = 35.0, 44.5

# Time window (Changed to 5 days to retrieve a full REAL 5-day forecast)
start_time = (datetime.datetime.now() - datetime.timedelta(hours=6))
end_time = (datetime.datetime.now() + datetime.timedelta(days=5))


def validate_copernicus_credentials_available():
    if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("CI") != "true":
        return
    missing = [name for name in REQUIRED_COPERNICUS_ENV if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing Copernicus Marine credential environment variable(s): "
            + ", ".join(missing)
        )


def subset_balearic_forecast(dataset_id, variables, output_filename, dry_run=False):
    return subset_with_retries(
        dataset_id=dataset_id,
        variables=variables,
        output_filename=output_filename,
        dry_run=dry_run,
    )


def subset_with_retries(dataset_id, variables, output_filename, dry_run=False):
    attempts = 1 if dry_run else max(1, COPERNICUS_MAX_ATTEMPTS)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return copernicusmarine.subset(
                dataset_id=dataset_id,
                variables=variables,
                minimum_longitude=lon_min,
                maximum_longitude=lon_max,
                minimum_latitude=lat_min,
                maximum_latitude=lat_max,
                start_datetime=start_time,
                end_datetime=end_time,
                output_directory=OUTPUT_DIR,
                output_filename=output_filename,
                file_format="netcdf",
                overwrite=True,
                dry_run=dry_run,
            )
        except Exception as error:
            last_error = error
            if attempt >= attempts or not is_retryable_copernicus_error(error):
                raise
            wait_seconds = COPERNICUS_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(
                f"Copernicus subset failed for {dataset_id} on attempt {attempt}/{attempts}: {error}. "
                f"Retrying in {wait_seconds:.0f}s."
            )
            time.sleep(wait_seconds)
    raise last_error


def is_retryable_copernicus_error(error):
    text = f"{type(error).__name__}: {error}".lower()
    non_retryable_markers = (
        "variable not found",
        "variables not found",
        "not found in dataset",
        "unknown variable",
        "does not exist in dataset",
    )
    if any(marker in text for marker in non_retryable_markers):
        return False
    retryable_markers = (
        "couldnotconnecttoauthenticationsystem",
        "connecttimeout",
        "connection",
        "timeout",
        "temporarily unavailable",
        "503",
        "502",
        "504",
        "429",
    )
    return any(marker in text for marker in retryable_markers)


def fetch_wave_forecast(dry_run=False):
    try:
        subset_balearic_forecast(
            dataset_id=WAV_ID,
            variables=WAVE_VARIABLES,
            output_filename="balearic_waves.nc",
            dry_run=dry_run,
        )
    except Exception as error:
        print(f"Wave partition download unavailable ({error}); retrying with core wave variables.")
        subset_balearic_forecast(
            dataset_id=WAV_ID,
            variables=CORE_WAVE_VARIABLES,
            output_filename="balearic_waves.nc",
            dry_run=dry_run,
        )


def _is_hidden_or_temp_path(path):
    parts = Path(path).parts
    return any(part.startswith(".") or part.startswith("._") or part == "__MACOSX" for part in parts)


def _classify_forecast_dataset(path):
    try:
        with xr.open_dataset(path) as ds:
            data_vars = {str(name).lower() for name in ds.data_vars}
            if {"uo", "vo"}.issubset(data_vars) or any(name in data_vars for name in {"uo", "vo", "current_u", "current_v"}):
                return "currents"
            if any(name in data_vars for name in {"vhm0", "vmdr", "vtpk", "wave_height", "wave_direction"}):
                return "waves"
    except Exception:
        pass
    name = Path(path).name.lower()
    if any(token in name for token in ("curr", "phy", "uvo")):
        return "currents"
    if any(token in name for token in ("wave", "wav", "sea")):
        return "waves"
    return None


def resolve_forecast_output_paths(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    waves_target = output_dir / "balearic_waves.nc"
    currents_target = output_dir / "balearic_currents.nc"
    if waves_target.exists() and currents_target.exists():
        print(
            f"Resolved canonical Copernicus outputs: waves={waves_target} currents={currents_target}",
            flush=True,
        )
        return {"waves_path": waves_target, "currents_path": currents_target}

    candidates = []
    for candidate in output_dir.rglob("*.nc"):
        if _is_hidden_or_temp_path(candidate):
            continue
        if candidate.name in {"balearic_waves.nc", "balearic_currents.nc"}:
            candidates.append(candidate)
            continue
        classification = _classify_forecast_dataset(candidate)
        if classification:
            candidates.append((classification, candidate))

    classified = {"waves": None, "currents": None}
    for item in candidates:
        if isinstance(item, tuple):
            classification, candidate = item
        else:
            candidate = item
            classification = "waves" if "wave" in candidate.name.lower() else "currents"
        if classification == "waves" and classified["waves"] is None:
            classified["waves"] = candidate
        elif classification == "currents" and classified["currents"] is None:
            classified["currents"] = candidate
    if classified["waves"] is None or classified["currents"] is None:
        raise FileNotFoundError(
            f"Could not resolve Copernicus forecast outputs in {output_dir}; "
            "expected wave and current NetCDF files."
        )

    if classified["waves"] != waves_target:
        shutil.copy2(classified["waves"], waves_target)
    if classified["currents"] != currents_target:
        shutil.copy2(classified["currents"], currents_target)
    print(
        "Resolved Copernicus forecast outputs: "
        f"waves={waves_target} (from {classified['waves']}), "
        f"currents={currents_target} (from {classified['currents']})",
        flush=True,
    )
    return {"waves_path": waves_target, "currents_path": currents_target}


def write_forecast_source_manifest(output_dir, metadata):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "forecast_source.json"
    manifest_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    return manifest_path


def get_balearic_forecast(dry_run=False, forecast_run_date=None):
    print("Fetching Western Mediterranean Currents (4.2km resolution)...")
    try:
        if not dry_run:
            validate_copernicus_credentials_available()

        # The current product contains horizontal velocity only. Sea-surface
        # height moved to a separate Copernicus dataset in version 202511 and
        # is not required by the route evidence pipeline.
        subset_balearic_forecast(
            dataset_id=PHY_ID,
            variables=["uo", "vo"],
            output_filename="balearic_currents.nc",
            dry_run=dry_run,
        )

        print("Fetching Western Mediterranean Waves (4.2km resolution)...")
        fetch_wave_forecast(dry_run=dry_run)
        if dry_run:
            print("\nDry run complete. No files were downloaded.")
            result = {
                "available": True,
                "waves_path": Path(OUTPUT_DIR) / "balearic_waves.nc",
                "currents_path": Path(OUTPUT_DIR) / "balearic_currents.nc",
                "forecast_source_status": "live",
                "forecast_run_date": forecast_run_date,
            }
            write_forecast_source_manifest(OUTPUT_DIR, {
                "id": "copernicus",
                "label": "Copernicus Marine Mediterranean forecast",
                "available": True,
                "forecast_source_status": "live",
                "forecast_run_date": forecast_run_date,
                "waves_path": str(result["waves_path"]),
                "currents_path": str(result["currents_path"]),
                "metadata": {
                    "wave_model": WAV_ID,
                    "current_model": PHY_ID,
                },
            })
            return result

        resolved = resolve_forecast_output_paths(OUTPUT_DIR)

        print(f"\nSuccess! Files downloaded to {OUTPUT_DIR}/")
        print(
            f"Canonical forecast files: waves={resolved['waves_path']} currents={resolved['currents_path']}",
            flush=True,
        )
        print("You can now open these with xarray to find the 'Certeza' for your captains.")
        result = {
            "available": True,
            "waves_path": resolved["waves_path"],
            "currents_path": resolved["currents_path"],
            "forecast_source_status": "live",
            "forecast_run_date": forecast_run_date,
        }
        write_forecast_source_manifest(OUTPUT_DIR, {
            "id": "copernicus",
            "label": "Copernicus Marine Mediterranean forecast",
            "available": True,
            "forecast_source_status": "live",
            "forecast_run_date": forecast_run_date,
            "waves_path": str(resolved["waves_path"]),
            "currents_path": str(resolved["currents_path"]),
            "metadata": {
                "wave_model": WAV_ID,
                "current_model": PHY_ID,
            },
        })
        return result

    except Exception as e:
        print(f"An error occurred: {e}")
        print("\nTroubleshooting tip: Run 'copernicusmarine login' again to refresh your token.")
        raise

if __name__ == "__main__":
    get_balearic_forecast()
