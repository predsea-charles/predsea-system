import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import xarray as xr


COPERNICUS_SOURCE = {
    "id": "copernicus",
    "label": "Copernicus Marine Mediterranean forecast",
}
SOCIB_SOURCE = {
    "id": "socib",
    "label": "SOCIB WMOP/SAPO forecast",
}
SOURCE_TIMEOUT_SECONDS = int(os.getenv("PREDSEA_SOURCE_TIMEOUT_SECONDS", "1800"))
SOURCE_ATTEMPTS = int(os.getenv("PREDSEA_SOURCE_ATTEMPTS", "1"))
NATIVE_SWAN_GCS_URI_ENV = "PREDSEA_NATIVE_SWAN_GCS_URI"
NATIVE_CURRENT_GCS_URI_ENV = "PREDSEA_NATIVE_CURRENT_GCS_URI"
NATIVE_SWAN_EXPECTED_HOURS_ENV = "PREDSEA_NATIVE_SWAN_FORECAST_HOURS"


def fetch_available_forecasts(fetch_data, output_dir=None, dry_run=False, forecast_run_date=None):
    """Fetch all configured forecast sources without letting one source block another."""
    output_dir = Path(output_dir or fetch_data.OUTPUT_DIR)
    timeout_seconds = int(os.getenv("PREDSEA_SOURCE_TIMEOUT_SECONDS", str(SOURCE_TIMEOUT_SECONDS)))
    attempts = int(os.getenv("PREDSEA_SOURCE_ATTEMPTS", str(SOURCE_ATTEMPTS)))
    source_configs = [
        (source_id, source_output_dir(source_id, output_dir))
        for source_id in configured_source_ids()
    ]
    sources = []
    for source_id, output_path in source_configs:
        print(f"Fetching forecast source: {source_id}", flush=True)
        print(f"  Output directory: {output_path}", flush=True)
        source = fetch_source_with_attempts(
            source_id,
            output_path,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            dry_run=dry_run,
            forecast_run_date=forecast_run_date,
        )
        if source.get("available"):
            waves_path = source.get("waves_path")
            currents_path = source.get("currents_path")
            print(
                f"Forecast source ready: {source_id} "
                f"(waves={waves_path}, currents={currents_path})",
                flush=True,
            )
        else:
            print(f"Forecast source unavailable: {source_id} ({source.get('error')})", flush=True)
        sources.append(source)
    native_source = fetch_native_swan_source(
        sources,
        output_dir,
        dry_run=dry_run,
        forecast_run_date=forecast_run_date,
    )
    if native_source is not None:
        sources.append(native_source)
    mark_preferred_source(
        sources,
        preferred_source_id="predsea_swan"
        if native_source and native_source.get("available")
        else "copernicus",
    )
    return sources


def _parse_gcs_uri(uri):
    if not uri.startswith("gs://") or "/" not in uri[5:]:
        raise ValueError(f"{NATIVE_SWAN_GCS_URI_ENV} must be a complete gs://bucket/object URI")
    return uri[5:].split("/", 1)


def _first_existing(dataset, names):
    return next((name for name in names if name in dataset.variables), None)


def adapt_native_swan_for_publication(source_path, destination_path, expected_hours=24):
    """Validate native SWAN output and write the stable route/API wave schema."""
    expected_timestamps = int(expected_hours) + 1
    destination_path = Path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(source_path) as source:
        time_name = _first_existing(source, ("time", "Time"))
        latitude_name = _first_existing(source, ("latitude", "lat"))
        longitude_name = _first_existing(source, ("longitude", "lon"))
        height_name = _first_existing(
            source, ("significant_wave_height", "VHM0", "hs", "hsign", "swh")
        )
        direction_name = _first_existing(
            source, ("mean_wave_direction", "VMDR", "dir", "mwd", "wave_direction")
        )
        period_name = _first_existing(
            source, ("peak_wave_period", "VTPK", "tp", "tps", "RTpeak")
        )
        missing = [
            label
            for label, value in (
                ("time", time_name),
                ("latitude", latitude_name),
                ("longitude", longitude_name),
                ("significant wave height", height_name),
                ("mean wave direction", direction_name),
                ("peak wave period", period_name),
            )
            if value is None
        ]
        if missing:
            raise ValueError("native SWAN output is missing " + ", ".join(missing))

        timestamp_count = int(source[time_name].size)
        if timestamp_count != expected_timestamps:
            raise ValueError(
                f"native SWAN output has {timestamp_count} timestamps; expected {expected_timestamps}"
            )
        decoded_times = np.asarray(source[time_name].values).astype("datetime64[s]")
        if decoded_times.size > 1:
            deltas = np.diff(decoded_times).astype("timedelta64[s]").astype(np.int64)
            if not np.all(deltas == 3600):
                raise ValueError("native SWAN output timestamps are not exactly hourly")

        for label, variable_name, lower, upper in (
            ("wave height", height_name, 0.0, 30.0),
            ("wave direction", direction_name, 0.0, 360.0),
            ("wave period", period_name, 0.0, 40.0),
        ):
            values = np.asarray(source[variable_name].values)
            finite = values[np.isfinite(values)]
            if not finite.size:
                raise ValueError(f"native SWAN {label} contains no finite values")
            if float(finite.min()) < lower or float(finite.max()) > upper:
                raise ValueError(
                    f"native SWAN {label} range [{finite.min()}, {finite.max()}] "
                    f"exceeds [{lower}, {upper}]"
                )

        publication = xr.Dataset(
            data_vars={
                "VHM0": source[height_name].copy(),
                "VMDR": source[direction_name].copy(),
                "VTPK": source[period_name].copy(),
            },
            coords={
                "time": source[time_name].copy(),
                "latitude": source[latitude_name].copy(),
                "longitude": source[longitude_name].copy(),
            },
            attrs={
                **source.attrs,
                "title": "PredSea native SWAN wave forecast",
                "provider": "predsea_swan",
                "native_model": "SWAN",
                "publication_schema": "predsea.route_wave.v1",
            },
        )
        publication["VHM0"].attrs.update(units="m")
        publication["VMDR"].attrs.update(units="degree")
        publication["VTPK"].attrs.update(units="s")
        publication.to_netcdf(destination_path)

    return {
        "timestamp_count": timestamp_count,
        "forecast_hours": int(expected_hours),
        "temporal_resolution_hours": 1,
        "native_variables": {
            "wave_height": height_name,
            "wave_direction": direction_name,
            "wave_period": period_name,
        },
    }


def adapt_current_fallback_for_publication(source_path, destination_path, required_times):
    """Subset a fallback current product to the exact native-wave timeline."""
    destination_path = Path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    required_times = np.asarray(required_times).astype("datetime64[ns]")
    with xr.open_dataset(source_path) as source:
        time_name = _first_existing(source, ("time", "Time", "time_counter"))
        latitude_name = _first_existing(source, ("latitude", "lat", "nav_lat"))
        longitude_name = _first_existing(source, ("longitude", "lon", "nav_lon"))
        u_name = _first_existing(source, ("uo", "current_u", "u"))
        v_name = _first_existing(source, ("vo", "current_v", "v"))
        missing = [
            label
            for label, value in (
                ("time", time_name),
                ("latitude", latitude_name),
                ("longitude", longitude_name),
                ("eastward current", u_name),
                ("northward current", v_name),
            )
            if value is None
        ]
        if missing:
            raise ValueError("current fallback is missing " + ", ".join(missing))
        available_times = np.asarray(source[time_name].values).astype("datetime64[ns]")
        missing_times = required_times[~np.isin(required_times, available_times)]
        if missing_times.size:
            rendered = ", ".join(str(value) for value in missing_times[:3])
            raise ValueError(f"current fallback does not cover native SWAN time(s): {rendered}")

        selected = source.sel({time_name: required_times}).load()
        for label, variable_name in (("eastward current", u_name), ("northward current", v_name)):
            values = np.asarray(selected[variable_name].values)
            finite = values[np.isfinite(values)]
            if not finite.size:
                raise ValueError(f"current fallback {label} contains no finite values")
            if float(np.abs(finite).max()) > 15.0:
                raise ValueError(f"current fallback {label} exceeds 15 m/s")
        rename = {}
        if time_name != "time":
            rename[time_name] = "time"
        if latitude_name != "latitude":
            rename[latitude_name] = "latitude"
        if longitude_name != "longitude":
            rename[longitude_name] = "longitude"
        if rename:
            selected = selected.rename(rename)
        selected.attrs.update(
            provider="copernicus",
            role="current_fallback_until_native_croco_is_validated",
            publication_schema="predsea.route_ocean.v1",
        )
        selected.to_netcdf(destination_path)
    return {"timestamp_count": int(required_times.size), "temporal_resolution_hours": 1}


def fetch_native_swan_source(sources, output_dir, dry_run=False, forecast_run_date=None):
    """Resolve one immutable native SWAN artifact and pair it with fallback currents."""
    uri = os.getenv(NATIVE_SWAN_GCS_URI_ENV, "").strip()
    if not uri:
        return None
    pinned_current_uri = os.getenv(NATIVE_CURRENT_GCS_URI_ENV, "").strip()
    currents_source = next(
        (source for source in sources if source.get("available") and source.get("currents_path")),
        None,
    )
    result = {
        "id": "predsea_swan",
        "label": "PredSea native SWAN 1 km waves with Copernicus current fallback",
        "available": False,
        "forecast_source_status": "staging_native",
        "forecast_run_date": forecast_run_date,
        "wave_provider": "predsea_swan",
        "current_provider": "copernicus"
        if pinned_current_uri
        else (currents_source.get("id") if currents_source else None),
        "metadata": {
            "native_wave_gcs_uri": uri,
            "current_fallback_gcs_uri": pinned_current_uri or None,
            "wave_model": "SWAN 41.51",
            "current_role": "fallback_until_native_croco_is_validated",
        },
    }
    if currents_source is None and not pinned_current_uri:
        result["error"] = "native SWAN publication requires an available current fallback"
        return result
    if dry_run:
        result["error"] = "dry-run does not download the configured native SWAN artifact"
        return result

    try:
        from google.cloud import storage

        bucket_name, object_name = _parse_gcs_uri(uri)
        native_dir = Path(output_dir) / "predsea_swan"
        raw_path = native_dir / "native_swan_raw.nc"
        publication_path = native_dir / "predsea_waves.nc"
        current_raw_path = native_dir / "current_fallback_raw.nc"
        current_publication_path = native_dir / "predsea_ocean_fallback.nc"
        native_dir.mkdir(parents=True, exist_ok=True)
        blob = storage.Client().bucket(bucket_name).blob(object_name)
        if not blob.exists():
            raise FileNotFoundError(f"immutable native SWAN artifact does not exist: {uri}")
        blob.download_to_filename(str(raw_path))
        expected_hours = int(os.getenv(NATIVE_SWAN_EXPECTED_HOURS_ENV, "24"))
        validation = adapt_native_swan_for_publication(
            raw_path, publication_path, expected_hours=expected_hours
        )
        if pinned_current_uri:
            current_bucket, current_object = _parse_gcs_uri(pinned_current_uri)
            current_blob = storage.Client().bucket(current_bucket).blob(current_object)
            if not current_blob.exists():
                raise FileNotFoundError(
                    f"immutable current fallback artifact does not exist: {pinned_current_uri}"
                )
            current_blob.download_to_filename(str(current_raw_path))
            with xr.open_dataset(publication_path) as waves:
                current_validation = adapt_current_fallback_for_publication(
                    current_raw_path,
                    current_publication_path,
                    waves["time"].values,
                )
            current_path = current_publication_path
            current_source_id = "copernicus"
            current_source_status = "pinned_immutable_fallback"
        else:
            current_validation = None
            current_path = Path(currents_source["currents_path"])
            current_source_id = currents_source.get("id")
            current_source_status = currents_source.get("forecast_source_status")
        result.update(
            available=True,
            waves_path=publication_path,
            currents_path=current_path,
        )
        result["metadata"].update(
            validation=validation,
            current_validation=current_validation,
            current_source_id=current_source_id,
            current_source_status=current_source_status,
        )
        print(
            f"Native SWAN source ready: {uri} "
            f"({validation['timestamp_count']} hourly timestamps); "
            f"currents={current_source_id}",
            flush=True,
        )
    except Exception as error:
        result["error"] = str(error)
    return result


def configured_source_ids():
    if os.getenv("PREDSEA_BYPASS_COPERNICUS") == "1":
        return []
    if os.getenv(NATIVE_SWAN_GCS_URI_ENV) and os.getenv(NATIVE_CURRENT_GCS_URI_ENV):
        return []
    return ["copernicus"]


def source_output_dir(source_id, output_dir):
    output_dir = Path(output_dir)
    if source_id == "socib":
        return output_dir / "socib_thredds"
    return output_dir / source_id


def fetch_source_with_attempts(source_id, output_dir, timeout_seconds, attempts=1, dry_run=False, forecast_run_date=None):
    attempts = max(1, int(attempts))
    last_source = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            print(f"Retrying forecast source: {source_id} (attempt {attempt}/{attempts})", flush=True)
        source = fetch_source_via_subprocess(
            source_id,
            output_dir,
            timeout_seconds=timeout_seconds,
            dry_run=dry_run,
            forecast_run_date=forecast_run_date,
        )
        if source.get("available"):
            if attempt > 1:
                source.setdefault("metadata", {})["fetch_attempt"] = attempt
            return source
        last_source = source
    if last_source is not None and attempts > 1:
        last_source["error"] = f"failed after {attempts} attempt(s): {last_source.get('error')}"
    return last_source or source_template(source_id)


def fetch_source_via_subprocess(source_id, output_dir, timeout_seconds, dry_run=False, forecast_run_date=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source = source_template(source_id)
    metadata_path = output_dir / "forecast_source.json"
    command = [
        sys.executable,
        str(Path(__file__).with_name("fetch_forecast_source.py")),
        "--source",
        source_id,
        "--output-dir",
        str(output_dir),
    ]
    if dry_run:
        command.append("--dry-run")
    if forecast_run_date:
        command.extend(["--forecast-run-date", str(forecast_run_date)])

    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).parent,
            timeout=timeout_seconds,
            check=False,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        source.update(available=False, error=f"{source_id} fetch timed out after {timeout_seconds}s")
        return source
    except Exception as error:
        source.update(available=False, error=str(error))
        return source

    if completed.stdout:
        print(completed.stdout.rstrip(), flush=True)
    if completed.stderr:
        print(completed.stderr.rstrip(), flush=True)

    if completed.returncode != 0:
        source.update(
            available=False,
            error=source_error_from_process(source_id, completed),
        )
        return source

    if not metadata_path.exists():
        source.update(available=False, error=f"{source_id} did not write {metadata_path.name}")
        return source

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["waves_path"] = Path(metadata["waves_path"])
    metadata["currents_path"] = Path(metadata["currents_path"])
    return metadata


def source_template(source_id):
    if source_id == "copernicus":
        return dict(COPERNICUS_SOURCE)
    if source_id == "socib":
        return dict(SOCIB_SOURCE)
    return {"id": source_id, "label": source_id}


def source_error_from_process(source_id, completed):
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if not output:
        return f"{source_id} fetch exited with code {completed.returncode}"
    return output[-1000:]


def fetch_copernicus_forecast(fetch_data, dry_run=False):
    source = dict(COPERNICUS_SOURCE)
    try:
        result = fetch_data.get_balearic_forecast(dry_run=dry_run) or {}
        output_dir = Path(fetch_data.OUTPUT_DIR)
        source.update(
            available=True,
            waves_path=Path(result.get("waves_path") or output_dir / "balearic_waves.nc"),
            currents_path=Path(result.get("currents_path") or output_dir / "balearic_currents.nc"),
            forecast_source_status=result.get("forecast_source_status", "live"),
            forecast_run_date=result.get("forecast_run_date"),
        )
    except Exception as error:
        source.update(available=False, error=str(error))
    return source


def fetch_socib_forecast(fetch_data, output_dir=None, dry_run=False):
    source = dict(SOCIB_SOURCE)
    try:
        import socib_thredds

        target_dir = Path(output_dir or fetch_data.OUTPUT_DIR) / "socib_thredds"
        result = socib_thredds.get_balearic_forecast(output_dir=target_dir, dry_run=dry_run)
        source.update(
            available=True,
            waves_path=Path(result["waves_path"]),
            currents_path=Path(result["currents_path"]),
            metadata=result.get("metadata", {}),
        )
    except Exception as error:
        source.update(available=False, error=str(error))
    return source


def mark_preferred_source(sources, preferred_source_id="copernicus"):
    available = [source for source in sources if source.get("available")]
    for source in sources:
        source["preferred"] = False
    if not available:
        return sources

    preferred = next(
        (source for source in available if source.get("id") == preferred_source_id),
        available[0],
    )
    preferred["preferred"] = True
    return sources


def source_manifest_entry(source):
    entry = {
        "id": source.get("id"),
        "label": source.get("label"),
        "available": bool(source.get("available")),
        "preferred": bool(source.get("preferred")),
        "forecast_source_status": source.get("forecast_source_status"),
        "forecast_run_date": source.get("forecast_run_date"),
    }
    if source.get("error"):
        entry["error"] = source["error"]
    if source.get("metadata"):
        entry["metadata"] = source["metadata"]
    if source.get("wave_provider"):
        entry["wave_provider"] = source["wave_provider"]
    if source.get("current_provider"):
        entry["current_provider"] = source["current_provider"]
    if source.get("waves_path"):
        entry["waves_path"] = str(source["waves_path"])
    if source.get("currents_path"):
        entry["currents_path"] = str(source["currents_path"])
    return entry
