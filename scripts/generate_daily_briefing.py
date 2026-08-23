import argparse
import inspect
import importlib.util
import json
import os
import shutil
import subprocess
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs"

human_path = str(HUMANINTHELOOP_DIR)
if human_path not in sys.path:
    sys.path.insert(0, human_path)

try:
    from api.config import PREDSEA_GCS_BUCKET
except ImportError:
    env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
    if env not in ("test", "prod"):
        env = "test"
    PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"

COPERNICUS_GCS_PREFIX = f"gs://{PREDSEA_GCS_BUCKET}/copernicus"
COPERNICUS_LATEST_WAVES_GCS_URI = f"{COPERNICUS_GCS_PREFIX}/waves_latest.nc"
COPERNICUS_LATEST_CURRENTS_GCS_URI = f"{COPERNICUS_GCS_PREFIX}/currents_latest.nc"
COPERNICUS_BUNDLE_GCS_PREFIX = f"{COPERNICUS_GCS_PREFIX}/bundles"
ROUTES_GCS_PREFIX = f"gs://{PREDSEA_GCS_BUCKET}/routes"
PRECOMPUTE_ROUTES_SCRIPT = HUMANINTHELOOP_DIR / "files" / "precompute_routes.py"
DEFAULT_LOCAL_TIMEZONE = "Europe/Madrid"
ROUTE_PRECOMPUTE_TIMEOUT_SECONDS = int(os.environ.get("PREDSEA_ROUTE_PRECOMPUTE_TIMEOUT_SECONDS", "1200"))
REQUIRED_TEXT_ARTIFACTS = (
    "daily_snapshot.json",
    "evidence.json",
)
# The Copernicus/WRF forcing this pipeline fetches already spans the whole
# Western Mediterranean basin (see fetch_data.py's subset bbox), not just the
# Balearics, so the default region label reflects actual basin-wide coverage
# rather than one sub-region. A route-specific region_id could be derived from
# each route's coordinates against simulation/marine/regions/*.json bboxes if
# per-region (rather than per-run) evidence scoping is ever needed.
DEFAULT_REGION_ID = "western_mediterranean"
REGIONAL_LIMITATIONS = (
    "No seabed type",
    "No depth/bathymetry",
    "No anchoring restrictions",
    "No nearby shelter search",
)

import source_lineage


@contextmanager
def pushd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def today_local(timezone_name=DEFAULT_LOCAL_TIMEZONE):
    if ZoneInfo is None:
        return datetime.now().date().isoformat()
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def current_time_local(timezone_name=DEFAULT_LOCAL_TIMEZONE):
    if ZoneInfo is None:
        return datetime.now().strftime("%H:%M")
    return datetime.now(ZoneInfo(timezone_name)).strftime("%H:%M")


def current_run_id_utc():
    return datetime.utcnow().strftime("%Y-%m-%dT%H%MZ")


def load_mvp_modules():
    human_path = str(HUMANINTHELOOP_DIR)
    if human_path not in sys.path:
        sys.path.insert(0, human_path)

    import bigquery_export
    import briefing
    import fetch_data
    import forecast_sources
    import ingest_atmosphere
    import ingest_observations
    import map_generator
    import place_weather
    import route_analysis
    import source_lineage as source_lineage_module
    import validation_archive

    return SimpleNamespace(
        briefing=briefing,
        bigquery_export=bigquery_export,
        fetch_data=fetch_data,
        forecast_sources=forecast_sources,
        ingest_atmosphere=ingest_atmosphere,
        ingest_observations=ingest_observations,
        map_generator=map_generator,
        place_weather=place_weather,
        route_analysis=route_analysis,
        source_lineage=source_lineage_module,
        validation_archive=validation_archive,
    )


def route_ids_from_args(route_analysis, route_ids):
    routes = route_analysis.load_routes()
    if not route_ids:
        return sorted(routes)

    unknown = sorted(set(route_ids) - set(routes))
    if unknown:
        available = ", ".join(sorted(routes))
        raise ValueError(f"Unknown route id(s): {', '.join(unknown)}. Available routes: {available}")
    return route_ids


def required_artifacts_for(skip_maps=False):
    artifacts = list(REQUIRED_TEXT_ARTIFACTS)
    if not skip_maps:
        artifacts.append("route_decision_map.png")
    return artifacts


def validate_route_artifacts(route_dir, skip_maps=False):
    missing = [name for name in required_artifacts_for(skip_maps) if not (route_dir / name).exists()]
    if missing:
        raise RuntimeError(f"{route_dir} missing required artifact(s): {', '.join(missing)}")


def resolve_humanintheloop_path(path):
    if path is None:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    search_roots = [
        HUMANINTHELOOP_DIR,
        Path.cwd(),
        PROJECT_ROOT,
    ]
    for root in search_roots:
        resolved = (Path(root) / candidate).resolve()
        if resolved.exists():
            return resolved
    return (HUMANINTHELOOP_DIR / candidate).resolve()


def upload_file_to_gcs(local_path, gcs_uri):
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected GCS URI, got {gcs_uri!r}")
    from google.cloud import storage

    bucket_name, blob_name = gcs_uri[5:].split("/", 1)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path))
    return gcs_uri


def normalize_route_precompute_path(path):
    if path is None:
        return None
    text = str(path)
    if text.startswith("gs://"):
        return text
    return str(Path(text).expanduser().resolve())


def upload_json_to_gcs(payload, gcs_uri):
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected GCS URI, got {gcs_uri!r}")
    from google.cloud import storage

    bucket_name, blob_name = gcs_uri[5:].split("/", 1)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(json.dumps(payload, indent=2), content_type="application/json")
    return gcs_uri


def copernicus_bundle_prefix(run_date):
    if not run_date:
        return None
    return f"{COPERNICUS_BUNDLE_GCS_PREFIX}/{run_date}"


def publish_latest_copernicus_files(source, run_date=None):
    if source.get("id", "copernicus") != "copernicus":
        print(
            "Skipping Copernicus compatibility publication for hybrid forecast "
            f"source {source.get('id')}; the canonical PredSea bundle retains "
            "per-component lineage.",
            flush=True,
        )
        return {}
    published = {}
    uploads = {
        "waves_path": COPERNICUS_LATEST_WAVES_GCS_URI,
        "currents_path": COPERNICUS_LATEST_CURRENTS_GCS_URI,
    }
    for key, gcs_uri in uploads.items():
        provider_key = "wave_provider" if key == "waves_path" else "current_provider"
        component_provider = source.get(provider_key) or source.get("id", "copernicus")
        if component_provider != "copernicus":
            print(
                f"Skipping Copernicus compatibility upload for {key}; "
                f"component provider is {component_provider}.",
                flush=True,
            )
            continue
        local_path = resolve_humanintheloop_path(source.get(key))
        if local_path is None:
            continue
        try:
            print(f"Publishing forecast file {key}: {local_path} -> {gcs_uri}", flush=True)
            upload_file_to_gcs(local_path, gcs_uri)
            print(f"Uploaded {key} to {gcs_uri}", flush=True)
            published[key] = gcs_uri
        except Exception as error:
            print(
                f"Warning: could not upload {key} to {gcs_uri}; "
                f"continuing with local path {local_path}. {error}",
                flush=True,
            )
            published[key] = str(local_path)
    bundle_prefix = copernicus_bundle_prefix(run_date or source.get("forecast_run_date"))
    if bundle_prefix and source.get("id", "copernicus") == "copernicus":
        bundle_manifest = {
            "id": source.get("id", "copernicus"),
            "label": source.get("label", "Copernicus Marine Mediterranean forecast"),
            "available": bool(source.get("available", True)),
            "forecast_source_status": source.get("forecast_source_status", "live"),
            "forecast_run_date": run_date or source.get("forecast_run_date"),
            "waves_path": str(source.get("waves_path")) if source.get("waves_path") else None,
            "currents_path": str(source.get("currents_path")) if source.get("currents_path") else None,
            "metadata": source.get("metadata", {}),
        }
        bundle_uploads = {
            "waves_path": f"{bundle_prefix}/balearic_waves.nc",
            "currents_path": f"{bundle_prefix}/balearic_currents.nc",
            "manifest": f"{bundle_prefix}/forecast_source.json",
        }
        for key, gcs_uri in bundle_uploads.items():
            try:
                if key == "manifest":
                    print(f"Publishing forecast manifest -> {gcs_uri}", flush=True)
                    upload_json_to_gcs(bundle_manifest, gcs_uri)
                    print(f"Uploaded forecast manifest to {gcs_uri}", flush=True)
                else:
                    local_path = resolve_humanintheloop_path(source.get(key))
                    if local_path is None:
                        continue
                    print(f"Publishing forecast bundle file {key}: {local_path} -> {gcs_uri}", flush=True)
                    upload_file_to_gcs(local_path, gcs_uri)
                    print(f"Uploaded forecast bundle file {key} to {gcs_uri}", flush=True)
            except Exception as error:
                print(
                    f"Warning: could not upload forecast bundle {key} to {gcs_uri}; continuing. {error}",
                    flush=True,
                )
    return published


def run_route_precompute(waves_path, currents_path, run_date, run_id):
    if not PRECOMPUTE_ROUTES_SCRIPT.exists():
        raise FileNotFoundError(f"Route precompute script not found: {PRECOMPUTE_ROUTES_SCRIPT}")

    waves_path = normalize_route_precompute_path(waves_path)
    currents_path = normalize_route_precompute_path(currents_path)
    print(
        "Route precompute inputs: "
        f"waves={waves_path} currents={currents_path} output={ROUTES_GCS_PREFIX} "
        f"run_date={run_date} run_id={run_id}",
        flush=True,
    )
    command = [
        sys.executable,
        str(PRECOMPUTE_ROUTES_SCRIPT),
        "--waves",
        str(waves_path),
        "--currents",
        str(currents_path),
        "--output-dir",
        ROUTES_GCS_PREFIX,
        "--date",
        run_date,
        "--forecast-run-utc",
        run_id,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            timeout=ROUTE_PRECOMPUTE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Route precompute timed out after {ROUTE_PRECOMPUTE_TIMEOUT_SECONDS}s"
        ) from error
    if completed.stdout:
        print(completed.stdout.rstrip(), flush=True)
    if completed.stderr:
        print(completed.stderr.rstrip(), flush=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Route precompute exited with code {completed.returncode}: "
            f"{(completed.stderr or completed.stdout or '').strip()}"
        )
    return True


def validate_forecast_available(forecast, route_id):
    missing = []
    if forecast.get("wave_max_m") is None:
        missing.append("wave forecast")
    if forecast.get("current_max_kn") is None:
        missing.append("current forecast")
    if missing:
        raise RuntimeError(f"Forecast layer unavailable for {route_id}: {', '.join(missing)}")


def safe_load_observations(briefing):
    try:
        return briefing.load_observations()
    except Exception as error:
        print(f"Warning: observations unavailable; continuing without buoy truth. {error}")
        return {}


def safe_load_observation_bundle(briefing):
    try:
        if hasattr(briefing, "load_observation_bundle"):
            return briefing.load_observation_bundle()
    except Exception as error:
        print(f"Warning: observation bundle unavailable; continuing with empty observations. {error}")
    return {"observations": safe_load_observations(briefing), "station_metadata": []}


def maybe_generate_route_map(map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False, resolution_label="Copernicus Med forecast grid"):
    if skip_maps:
        return None
    output_path = route_dir / "route_decision_map.png"
    map_generator.generate_route_decision_map(
        waves_path=waves_path,
        currents_path=currents_path,
        route=route,
        snapshot=snapshot,
        output_path=output_path,
    )
    return output_path


def maybe_generate_leaflet_overlays(run_dir, waves_path, currents_path, skip_maps=False):
    if skip_maps:
        return None
    overlay_generator = load_leaflet_overlay_generator()
    return overlay_generator.generate_leaflet_overlays(
        waves_path,
        currents_path,
        run_dir,
        variables=sorted(overlay_generator.VARIABLES),
    )


def load_publication_map_generator():
    module_path = PROJECT_ROOT / "scripts" / "generate_ocean_conditions_map.py"
    spec = importlib.util.spec_from_file_location("predsea_publication_map_generator", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_leaflet_overlay_generator():
    module_path = PROJECT_ROOT / "scripts" / "generate_leaflet_overlays.py"
    spec = importlib.util.spec_from_file_location("predsea_leaflet_overlay_generator", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def map_supported_modes(available_variables):
    modes = ["route_question"]
    if available_variables:
        modes.extend(["location_question", "map_inspect"])
    return modes


def collect_map_variable_metadata(run_dir):
    maps_dir = run_dir / "maps"
    if not maps_dir.exists():
        return {}

    variables = {}
    for index_path in sorted(maps_dir.glob("*/index.json")):
        index = json.loads(index_path.read_text(encoding="utf-8"))
        overlays = index.get("overlays") or []
        times = sorted(overlay["time"] for overlay in overlays if overlay.get("time"))
        first_with_bounds = next((overlay for overlay in overlays if overlay.get("bounds")), None)
        variable = index.get("variable") or index_path.parent.name
        variables[variable] = {
            "units": index.get("units"),
            "time_count": len(overlays),
            "time_start": times[0] if times else None,
            "time_end": times[-1] if times else None,
            "bounds": first_with_bounds.get("bounds") if first_with_bounds else None,
            "color_scale": index.get("color_scale"),
            "opacity": index.get("opacity"),
            "index_path": str(index_path.relative_to(run_dir)),
        }
    return variables


def write_regional_evidence(run_dir, run_date, run_id, routes, forecast_sources=None, region_id=DEFAULT_REGION_ID):
    available_variables = collect_map_variable_metadata(run_dir)
    regional_evidence = {
        "region_id": region_id,
        "run_date": run_date,
        "run_id": run_id,
        "supported_modes": map_supported_modes(available_variables),
        "routes": routes,
        "forecast_sources": forecast_sources or [],
        "available_variables": available_variables,
        "limitations": list(REGIONAL_LIMITATIONS),
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (run_dir / "regional_evidence.json").write_text(json.dumps(regional_evidence, indent=2, default=str), encoding="utf-8")
    return regional_evidence


def write_predsea_forecast_bundle(
    run_dir,
    run_date,
    run_id,
    preferred_source,
    atmospheric_context,
):
    """Publish a stable PredSea-owned data contract for API consumers.

    Upstream provider files remain traceable, but the API reads these
    run-scoped PredSea objects rather than depending on a provider-specific
    directory or another Cloud Run container's local filesystem.
    """
    bundle_dir = Path(run_dir) / "forecast_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    components = {}

    for source_key, bundle_name, variables in (
        (
            "waves_path",
            "predsea_waves.nc",
            ["wave_height", "wave_direction", "wave_period"],
        ),
        (
            "currents_path",
            "predsea_ocean.nc",
            ["current_u", "current_v", "sea_temperature", "sea_level"],
        ),
    ):
        source_path = resolve_humanintheloop_path(preferred_source.get(source_key))
        if source_path is None or not source_path.exists():
            continue
        destination = bundle_dir / bundle_name
        shutil.copy2(source_path, destination)
        components[source_key] = {
            "path": f"forecast_bundle/{bundle_name}",
            "provider": preferred_source.get(
                "wave_provider" if source_key == "waves_path" else "current_provider",
                preferred_source.get("id"),
            ),
            "provider_status": preferred_source.get("forecast_source_status", "live"),
            "variables": variables,
        }

    wind_result = atmospheric_context.get("wind_result", {})
    wind_path = wind_result.get("dataset_path")
    atmosphere_metadata = {}
    if wind_path and Path(wind_path).exists():
        destination = bundle_dir / "predsea_atmosphere.nc"
        shutil.copy2(wind_path, destination)
        try:
            import xarray as xr

            with xr.open_dataset(wind_path, decode_times=False) as atmosphere:
                time_count = int(atmosphere.sizes.get("Time", atmosphere.sizes.get("time", 0)))
                atmosphere_metadata["timestamp_count"] = time_count
                if time_count:
                    atmosphere_metadata["horizon_hours"] = max(0, time_count - 1)
                if "XLAT" in atmosphere and "XLONG" in atmosphere:
                    atmosphere_metadata["coverage"] = {
                        "min_latitude": float(atmosphere["XLAT"].min()),
                        "max_latitude": float(atmosphere["XLAT"].max()),
                        "min_longitude": float(atmosphere["XLONG"].min()),
                        "max_longitude": float(atmosphere["XLONG"].max()),
                    }
        except Exception as error:
            atmosphere_metadata["inspection_error"] = str(error)
        components["atmosphere"] = {
            "path": "forecast_bundle/predsea_atmosphere.nc",
            "provider": wind_result.get("source", "predsea_wrf"),
            "resolution_km": wind_result.get("resolution_km"),
            "variables": ["wind_u_10m", "wind_v_10m", "air_temperature", "pressure"],
            **atmosphere_metadata,
        }

    manifest = {
        "schema_version": "predsea.forecast_bundle.v1",
        "run_date": run_date,
        "run_id": run_id,
        "ownership": "PredSea",
        "product": {
            "region_id": os.environ.get("PREDSEA_REGION_ID", DEFAULT_REGION_ID),
            "atmosphere_resolution_km": wind_result.get("resolution_km"),
            "forecast_hours": atmosphere_metadata.get("horizon_hours"),
            "temporal_resolution_hours": 1,
        },
        "components": components,
        "lineage": {
            "marine_source": preferred_source.get("id"),
            "wave_source": preferred_source.get("wave_provider", preferred_source.get("id")),
            "ocean_source": preferred_source.get("current_provider", preferred_source.get("id")),
            "atmosphere_source": wind_result.get("source"),
        },
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str),
        encoding="utf-8",
    )
    return manifest


def regional_evidence_manifest_entry(regional_evidence):
    return {
        "path": "regional_evidence.json",
        "region_id": regional_evidence["region_id"],
        "supported_modes": regional_evidence["supported_modes"],
        "available_variables": sorted(regional_evidence["available_variables"]),
    }


def validation_manifest_entry(validation_summary):
    if not validation_summary:
        return None
    return {
        "path": "validation/validation_summary.json",
        "observation_samples_path": "validation/observation_samples.jsonl",
        "forecast_index_path": "validation/forecast_index.jsonl",
        "matched_validation_path": "validation/matched_validation.jsonl",
        "station_metadata_path": "validation/station_metadata.jsonl",
        "observation_rows": validation_summary.get("observation_rows", 0),
        "forecast_rows": validation_summary.get("forecast_rows", 0),
        "matched_rows": validation_summary.get("matched_rows", 0),
        "station_metadata_rows": validation_summary.get("station_metadata_rows", 0),
        "matched_variables": validation_summary.get("matched_variables", {}),
    }


def load_preferred_snapshots(run_dir, route_ids):
    snapshots = {}
    for route_id in route_ids:
        snapshot_path = Path(run_dir) / route_id / "daily_snapshot.json"
        snapshots[route_id] = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return snapshots


def write_manifest(run_dir, run_date, run_id, routes, vessel_class, forecast_sources=None, regional_evidence=None, validation=None, publication_phase="high_resolution", wrf_status="complete"):
    manifest = {
        "run_date": run_date,
        "run_id": run_id,
        "route_count": len(routes),
        "routes": routes,
        "vessel_class": vessel_class,
        "forecast_sources": forecast_sources or [],
        "regional_evidence": regional_evidence,
        "validation": validation,
        "publication_phase": publication_phase,
        "wrf_status": wrf_status,
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def write_latest_run(day_dir, run_date, run_id, routes, vessel_class, regional_evidence=None, validation=None, publication_phase="high_resolution", wrf_status="complete"):
    latest = {
        "run_date": run_date,
        "run_id": run_id,
        "path": f"runs/{run_id}",
        "route_count": len(routes),
        "routes": routes,
        "vessel_class": vessel_class,
        "regional_evidence": regional_evidence,
        "validation": validation,
        "publication_phase": publication_phase,
        "wrf_status": wrf_status,
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (day_dir / "latest_run.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")
    return latest


def publish_run_to_gcs(run_dir, day_dir, run_date, run_id, bucket_name=None):
    """Publish a generated run to the configured GCS or S3 evidence store."""
    storage_backend = os.environ.get("PREDSEA_STORAGE_BACKEND", "gcs").lower()
    if storage_backend == "s3":
        bucket_name = bucket_name or os.environ.get("PREDSEA_S3_BUCKET")
        if not bucket_name:
            print("No PREDSEA_S3_BUCKET configured; keeping briefing artifacts local.", flush=True)
            return []
        import boto3
        client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
        uploaded = []
        for local_path in sorted(Path(run_dir).rglob("*")):
            if local_path.is_file():
                relative_path = local_path.relative_to(run_dir).as_posix()
                object_name = f"predictions/{run_date}/runs/{run_id}/{relative_path}"
                client.upload_file(str(local_path), bucket_name, object_name, ExtraArgs={"ServerSideEncryption": "AES256"})
                uploaded.append(object_name)
        latest_path = Path(day_dir) / "latest_run.json"
        latest_object = f"predictions/{run_date}/latest_run.json"
        client.upload_file(str(latest_path), bucket_name, latest_object, ExtraArgs={"ServerSideEncryption": "AES256", "ContentType": "application/json"})
        uploaded.append(latest_object)
        print(f"Published {len(uploaded)} briefing artifacts to s3://{bucket_name}/predictions/{run_date}/", flush=True)
        return uploaded

    bucket_name = bucket_name or os.environ.get("PREDSEA_GCS_BUCKET")
    if not bucket_name:
        print("No PREDSEA_GCS_BUCKET configured; keeping briefing artifacts local.", flush=True)
        return []

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    uploaded = []
    for local_path in sorted(Path(run_dir).rglob("*")):
        if not local_path.is_file():
            continue
        relative_path = local_path.relative_to(run_dir).as_posix()
        object_name = f"predictions/{run_date}/runs/{run_id}/{relative_path}"
        bucket.blob(object_name).upload_from_filename(str(local_path))
        uploaded.append(object_name)

    latest_path = Path(day_dir) / "latest_run.json"
    latest_object = f"predictions/{run_date}/latest_run.json"
    bucket.blob(latest_object).upload_from_filename(str(latest_path))
    uploaded.append(latest_object)
    print(
        f"Published {len(uploaded)} briefing artifacts to gs://{bucket_name}/predictions/{run_date}/",
        flush=True,
    )
    return uploaded


def write_bigquery_export_diagnostics(run_dir, name, result):
    if not result:
        return None
    diagnostics = {
        "name": name,
        "status": result.get("status"),
        "reason": result.get("reason"),
        "project_id": result.get("project_id"),
        "dataset_id": result.get("dataset_id"),
        "table_id": result.get("table_id"),
        "observation_rows": result.get("observation_rows", 0),
        "forecast_rows": result.get("forecast_rows", 0),
        "exported_rows": result.get("exported_rows", 0),
        "failed_rows": result.get("failed_rows", 0),
        "error_messages": result.get("error_messages", []),
        "failed_row_samples": result.get("failed_row_samples", []),
        "insert_errors": result.get("insert_errors", []),
        "response_status": result.get("response_status"),
        "response_body": result.get("response_body"),
        "traceback": result.get("traceback"),
    }
    validation_dir = Path(run_dir) / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_path = validation_dir / f"{name}_bigquery_diagnostics.json"
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2, default=str), encoding="utf-8")
    summary = f"{name}: {result.get('status')} (obs={diagnostics['observation_rows']}, forecast={diagnostics['forecast_rows']}, exported={diagnostics['exported_rows']})"
    if diagnostics["reason"]:
        summary += f" reason={diagnostics['reason']}"
    print(summary, flush=True)
    if diagnostics["failed_rows"]:
        print(
            f"{name} failed rows: {diagnostics['failed_rows']}",
            flush=True,
        )
    for message in diagnostics["error_messages"][:5]:
        print(f"{name} error: {message}", flush=True)
    for sample in diagnostics["failed_row_samples"][:3]:
        print(f"{name} failed row sample: {json.dumps(sample, default=str)}", flush=True)
    print(f"{name} diagnostics written to {diagnostics_path}", flush=True)
    return diagnostics


def fetch_forecast_sources(modules, run_dir, run_date=None):
    if hasattr(modules, "forecast_sources"):
        fetch_forecasts = modules.forecast_sources.fetch_available_forecasts
        try:
            return fetch_forecasts(
                modules.fetch_data,
                output_dir=Path(modules.fetch_data.OUTPUT_DIR),
                dry_run=False,
                forecast_run_date=run_date,
            )
        except TypeError as error:
            if "forecast_run_date" not in str(error):
                raise
            return fetch_forecasts(
                modules.fetch_data,
                output_dir=Path(modules.fetch_data.OUTPUT_DIR),
                dry_run=False,
            )

    forecast_kwargs = {"dry_run": False}
    try:
        signature = inspect.signature(modules.fetch_data.get_balearic_forecast)
        if "forecast_run_date" in signature.parameters:
            forecast_kwargs["forecast_run_date"] = run_date
    except (TypeError, ValueError):
        pass
    forecast_files = modules.fetch_data.get_balearic_forecast(**forecast_kwargs) or {}
    return [
        {
            "id": "copernicus",
            "label": "Copernicus Marine Mediterranean forecast",
            "available": True,
            "preferred": True,
            "forecast_source_status": forecast_files.get("forecast_source_status", "live"),
            "forecast_run_date": forecast_files.get("forecast_run_date"),
            "waves_path": Path(forecast_files.get("waves_path") or Path(modules.fetch_data.OUTPUT_DIR) / "balearic_waves.nc"),
            "currents_path": Path(forecast_files.get("currents_path") or Path(modules.fetch_data.OUTPUT_DIR) / "balearic_currents.nc"),
        }
    ]


def available_forecast_sources(sources):
    return [source for source in sources if source.get("available")]


def preferred_forecast_source(sources):
    available = available_forecast_sources(sources)
    if not available:
        return None
    return next((source for source in available if source.get("preferred")), available[0])


def load_forecast_manifest(candidate_dir):
    manifest_path = Path(candidate_dir) / "forecast_source.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def forecast_manifest_matches_run_date(manifest, run_date):
    if not manifest:
        return False
    if not run_date:
        return True
    candidate_dates = (
        manifest.get("forecast_run_date"),
        manifest.get("run_date"),
        manifest.get("forecast_bundle_date"),
    )
    return any(candidate == run_date for candidate in candidate_dates if candidate)


def load_cached_copernicus_bundle_from_gcs(run_date):
    if not run_date:
        return None
    bundle_prefix = f"{COPERNICUS_BUNDLE_GCS_PREFIX}/{run_date}"
    try:
        from google.cloud import storage
    except Exception:
        return None

    try:
        client = storage.Client()
        bucket_name, prefix = bundle_prefix[5:].split("/", 1)
        bucket = client.bucket(bucket_name)
        manifest_blob = bucket.blob(f"{prefix}/forecast_source.json")
        if not manifest_blob.exists():
            return None
        manifest = json.loads(manifest_blob.download_as_text(encoding="utf-8"))
        if not forecast_manifest_matches_run_date(manifest, run_date):
            return None
        temp_dir = Path(tempfile.mkdtemp(prefix=f"predsea-copernicus-{run_date}-"))
        waves_path = temp_dir / "balearic_waves.nc"
        currents_path = temp_dir / "balearic_currents.nc"
        bucket.blob(f"{prefix}/balearic_waves.nc").download_to_filename(str(waves_path))
        bucket.blob(f"{prefix}/balearic_currents.nc").download_to_filename(str(currents_path))
        return {
            "id": "copernicus",
            "label": "Cached Copernicus Marine Mediterranean forecast",
            "available": True,
            "preferred": True,
            "cached": True,
            "forecast_source_status": "cached",
            "forecast_run_date": run_date,
            "waves_path": waves_path,
            "currents_path": currents_path,
            "metadata": {
                "source_type": "cached_bundle",
                "cache_source": "gcs",
                "cache_prefix": bundle_prefix,
                "manifest_path": f"{bundle_prefix}/forecast_source.json",
            },
        }
    except Exception as error:
        print(f"Warning: could not load cached Copernicus bundle from GCS for {run_date}: {error}", flush=True)
        return None


def cached_forecast_source(fetch_data, run_date=None):
    output_dir = Path(getattr(fetch_data, "OUTPUT_DIR", PROJECT_ROOT / "mvp_data"))
    candidate_dirs = [
        output_dir,
        output_dir / "copernicus",
        PROJECT_ROOT / "mvp_data",
        PROJECT_ROOT / "mvp_data" / "copernicus",
    ]
    seen = set()
    for candidate_dir in candidate_dirs:
        candidate_dir = Path(candidate_dir).resolve()
        if candidate_dir in seen:
            continue
        seen.add(candidate_dir)
        manifest = load_forecast_manifest(candidate_dir)
        if manifest and not forecast_manifest_matches_run_date(manifest, run_date):
            continue
        waves_path = candidate_dir / "balearic_waves.nc"
        currents_path = candidate_dir / "balearic_currents.nc"
        if waves_path.exists() and currents_path.exists() and forecast_manifest_matches_run_date(manifest, run_date):
            print(
                "Warning: no live forecast source available; reusing cached Copernicus bundle "
                f"from {candidate_dir}.",
                flush=True,
            )
            return {
                "id": "copernicus",
                "label": "Cached Copernicus Marine Mediterranean forecast",
                "available": True,
                "preferred": True,
                "cached": True,
                "forecast_source_status": "cached",
                "forecast_run_date": run_date if run_date else (manifest.get("forecast_run_date") if manifest else None),
                "waves_path": waves_path,
                "currents_path": currents_path,
                "metadata": {
                    "source_type": "cached_bundle",
                    "cache_dir": str(candidate_dir),
                    "manifest_path": str(candidate_dir / "forecast_source.json") if manifest else None,
                },
            }
    gcs_cached = load_cached_copernicus_bundle_from_gcs(run_date)
    if gcs_cached:
        print(
            "Warning: no live forecast source available; reusing cached Copernicus bundle "
            f"from GCS prefix {gcs_cached['metadata'].get('cache_prefix')}.",
            flush=True,
        )
        return gcs_cached
    return None


def source_manifest_entries(modules, sources):
    if hasattr(modules, "forecast_sources"):
        entries = []
        for source in sources:
            entry = modules.forecast_sources.source_manifest_entry(source)
            if source.get("metadata") and "metadata" not in entry:
                entry["metadata"] = source["metadata"]
            if source.get("cached") and "metadata" not in entry:
                entry["metadata"] = {
                    "source_type": "cached_bundle",
                    "cache_dir": str(Path(source.get("waves_path", "")).parent) if source.get("waves_path") else None,
                }
            entries.append(entry)
        return entries
    return [
        {
            "id": source.get("id"),
            "label": source.get("label"),
            "available": bool(source.get("available")),
            "preferred": bool(source.get("preferred")),
        }
        for source in sources
    ]


def atmospheric_ingestion_enabled():
    return os.environ.get("PREDSEA_ENABLE_ATMOSPHERIC_INGESTION", "0") == "1"


def fetch_atmospheric_context(modules, run_dir):
    """
    Fetch atmospheric wind data.
    First, try to find a local WRF file or download from GCS.
    Then, fall back to external providers if enabled.
    """
    # 1. Try WRF (Tier 0)
    wrf_result = _fetch_wrf_wind_context(modules, run_dir)
    if wrf_result.get("available"):
        print(f"✅ WRF Wind data available: {wrf_result.get('dataset_path')}")
        return {
            "enabled": True,
            "wind_result": wrf_result,
            "wind_lineage": modules.ingest_atmosphere.lineage_for_wind_result(wrf_result),
            "atmospheric_sources": [wrf_result],
        }

    # 2. Fallback to external providers
    if os.environ.get("PREDSEA_ENABLE_ATMOSPHERIC_INGESTION") != "true" and os.environ.get("PREDSEA_ENABLE_ATMOSPHERIC_INGESTION") != "1":
        return {
            "enabled": False,
            "wind_result": {"available": False, "error": "atmospheric ingestion disabled; WRF also unavailable"},
            "wind_lineage": {"source": None, "resolution_km": None, "status": "not_configured"},
            "atmospheric_sources": [],
        }

    output_dir = run_dir / "atmosphere"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Fetching atmospheric wind data to {output_dir}...")
    try:
        context = modules.ingest_atmosphere.run_atmospheric_ingestion(output_dir=output_dir)
        context["enabled"] = True
        return context
    except Exception as error:
        return {
            "enabled": True,
            "wind_result": {"available": False, "source": None, "error": str(error)},
            "wind_lineage": {
                "source": None,
                "resolution_km": None,
                "status": "error",
                "tier": None,
            },
            "atmospheric_sources": [],
        }


def _fetch_wrf_wind_context(modules, run_dir):
    """Attempt to find WRF wind data for all domains (d03-d07) locally or download from GCS."""
    from datetime import datetime
    run_date = os.environ.get("PREDSEA_RUN_DATE") or datetime.utcnow().strftime("%Y-%m-%d")
    run_id = os.environ.get("PREDSEA_RUN_ID") or datetime.utcnow().strftime("%Y-%m-%dT%H%MZ")
    bucket_name = os.environ.get("PREDSEA_GCS_BUCKET")
    
    output_dir = run_dir / "atmosphere"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Prefer the active operational d02 (3 km Western Mediterranean) while
    # retaining support for archived/experimental regional domains.
    available_domains = []
    
    domains_meta = {
        "d02": {"label": "PredSea Western Mediterranean 3km", "region": "Western Mediterranean", "resolution_km": 3.0},
        "d03": {"label": "PredSea Balearic 1km", "region": "Balearics"},
        "d04": {"label": "PredSea French Coast 1km", "region": "France"},
        "d05": {"label": "PredSea Corsica/Sardinia 1km", "region": "Corsica/Sardinia"},
        "d06": {"label": "PredSea Ligurian/Tuscan 1km", "region": "Italy North"},
        "d07": {"label": "PredSea Tyrrhenian 1km", "region": "Italy South"},
    }

    # Helper to download specific domain
    def get_domain(dom_id):
        local_path = output_dir / f"wrf_{dom_id}.nc"
        if local_path.exists():
            return local_path
        if not bucket_name:
            return None
            
        try:
            from model_output_discovery import candidate_blobs, download_first_valid
            from wrf_forecast_ingestor import download_and_combine_wrf_domain
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            prefix = f"predictions/{run_date}/runs/{run_id}/"
            blobs = list(bucket.list_blobs(prefix=prefix))
            if not blobs:
                prefix = f"predictions/{run_date}/"
                blobs = list(bucket.list_blobs(prefix=prefix))
            
            domain_candidates = [
                blob for blob in candidate_blobs(blobs, "wrf") if dom_id in Path(blob.name).name
            ]
            hourly_candidates = [
                blob for blob in domain_candidates
                if Path(blob.name).name.lower().startswith(f"wrfout_{dom_id}_")
            ]
            if hourly_candidates:
                timestamp_count = download_and_combine_wrf_domain(hourly_candidates, local_path)
                print(
                    f"📥 Downloaded and combined {timestamp_count} validated WRF {dom_id} timestamps "
                    f"({domains_meta[dom_id]['region']}) from gs://{bucket_name}"
                )
                return local_path

            target_blob = download_first_valid(domain_candidates, "wrf", local_path)

            if target_blob:
                print(
                    f"📥 Downloaded validated WRF {dom_id} ({domains_meta[dom_id]['region']}): "
                    f"gs://{bucket_name}/{target_blob.name}"
                )
                return local_path
        except Exception as e:
            print(f"⚠️ Warning: Failed to download WRF {dom_id} from GCS: {e}")
        return None

    # Try to fetch all domains
    for dom_id, meta in domains_meta.items():
        path = get_domain(dom_id)
        if path:
            available_domains.append({
                "available": True,
                "id": f"predsea_wrf_{dom_id}",
                "source": f"predsea_wrf_{dom_id}",
                "label": meta["label"],
                "tier": 0,
                "resolution_km": meta.get("resolution_km", 1.0),
                "dataset_path": str(path),
                "domain": dom_id,
            })
            
    if available_domains:
        return build_wrf_wind_result(available_domains)
        
    return {"available": False, "error": "No high-res WRF domains found"}


def build_wrf_wind_result(available_domains):
    """Build a JSON-safe primary result without a primary -> list -> primary cycle."""
    domains = [dict(domain) for domain in available_domains]
    primary = dict(domains[0])
    primary["all_domains"] = domains
    return primary


def ocean_lineage_for_source(source):
    source_id = source.get("id")
    if source_id == "socib":
        return {
            "source": "socib_wmop_sapo",
            "resolution_km": source.get("metadata", {}).get("resolution_km"),
            "status": "active",
        }
    return {
        "source": "copernicus_med",
        "resolution_km": 4.0,
        "status": "active",
    }


def ground_truth_lineage_for_observations(observations):
    if observations:
        return {
            "source": "puertos_observations",
            "status": "matched_successfully",
            "station_count": len(observations),
        }
    return {
        "source": None,
        "status": "unavailable",
        "station_count": 0,
    }


def data_lineage_for_snapshot(source, atmospheric_context, observations):
    return {
        "wind_forecast": atmospheric_context.get(
            "wind_lineage",
            {
                "source": None,
                "resolution_km": None,
                "status": "not_configured",
                "tier": None,
            },
        ),
        "ocean_forecast": ocean_lineage_for_source(source),
        "ground_truth_validation": ground_truth_lineage_for_observations(observations),
    }


def annotate_snapshot_with_source(snapshot, source):
    snapshot["forecast_source"] = {
        "id": source.get("id"),
        "label": source.get("label"),
        "preferred": bool(source.get("preferred")),
    }
    if source.get("cached"):
        snapshot["forecast_source"]["cached"] = True
    if source.get("metadata"):
        snapshot["forecast_source"]["metadata"] = source["metadata"]
    return snapshot


def annotate_snapshot_with_lineage(snapshot, source, atmospheric_context, observations):
    snapshot["data_lineage"] = data_lineage_for_snapshot(source, atmospheric_context, observations)
    return snapshot


def annotate_snapshot_with_source_summary(snapshot, source_inventory, observations):
    summary = source_lineage.summarize_sources(
        snapshot=snapshot,
        observations=observations,
        source_inventory=source_inventory,
        data_lineage=snapshot.get("data_lineage"),
    )
    snapshot["source_summary"] = summary
    snapshot.setdefault("data_lineage", {})
    snapshot["data_lineage"]["source_summary"] = summary
    snapshot["data_lineage"]["source_inventory"] = source_inventory
    return snapshot


def resolution_label_for(source):
    source_id = source.get("id")
    if source_id == "socib":
        return "SOCIB WMOP/SAPO forecast grid"
    return "Copernicus Med forecast grid"


def select_best_wrf_domain_for_route(route, atmospheric_context):
    """
    Given a route and the available WRF domains, return the best domain path.
    Uses the highest resolution domain that spatially contains the route points.
    """
    if not atmospheric_context or not atmospheric_context.get("enabled"):
        return None
        
    wind_result = atmospheric_context.get("wind_result", {})
    all_domains = wind_result.get("all_domains", [])
    if not all_domains:
        return wind_result.get("dataset_path") # Fallback to primary

    # For each domain, we check if it covers the route points.
    # For now, we use a simple heuristic: d04 is France, d06/d07 is Italy.
    # In the future, we can open the file and check coordinates.
    route_name_lower = route.get("name", "").lower()
    
    # Heuristic mapping based on names if we don't want to open every NetCDF file here
    if any(k in route_name_lower for k in ["marseille", "cannes", "nice", "st tropez", "saint-tropez", "eze", "antibes", "toulon", "monaco"]):
        target_dom = "d04"
    elif any(k in route_name_lower for k in ["portofino", "genoa", "savona", "la spezia", "livorno", "tuscany", "elba"]):
        target_dom = "d06"
    elif any(k in route_name_lower for k in ["capri", "amalfi", "naples", "ischia", "procida", "salerno", "sicily", "lipari", "vulcano", "stromboli", "palermo", "messina"]):
        target_dom = "d07"
    elif any(k in route_name_lower for k in ["corsica", "sardinia", "ajaccio", "bonifacio", "olbia", "porto cervo"]):
        target_dom = "d05"
    else:
        target_dom = "d03" # Balearics default
        
    for dom in all_domains:
        if dom.get("domain") == target_dom:
            return dom.get("dataset_path")
            
    # If target not found, return the first one available
    return all_domains[0].get("dataset_path") if all_domains else wind_result.get("dataset_path")


def copy_preferred_route_artifacts(source_route_dir, preferred_route_dir):
    try:
        if preferred_route_dir.exists():
            shutil.rmtree(preferred_route_dir)
        shutil.copytree(source_route_dir, preferred_route_dir)
    except Exception as e:
        print(f"⚠️ Warning: Could not copy preferred route artifacts: {e}")


def generate_route_artifacts_for_source(
    modules,
    source,
    source_root_dir,
    selected_route_ids,
    routes,
    observations,
    vessel_class,
    question,
    location_label,
    current_time,
    skip_maps,
    atmospheric_context=None,
    source_inventory=None,
):
    waves_path = Path(source["waves_path"])
    currents_path = Path(source["currents_path"])
    maybe_generate_leaflet_overlays(source_root_dir, waves_path, currents_path, skip_maps=skip_maps)
    generated_routes = {}

    for route_id in selected_route_ids:
        route = routes[route_id]
        wind_path = select_best_wrf_domain_for_route(route, atmospheric_context)
        forecast = modules.route_analysis.forecast_summary_from_files(
            waves_path,
            currents_path,
            wind_path=wind_path,
            route=route,
        )
        validate_forecast_available(forecast, route_id)
        snapshot = modules.route_analysis.build_route_snapshot(
            observations,
            forecast,
            route=route,
            vessel_class=vessel_class,
        )
        annotate_snapshot_with_source(snapshot, source)
        annotate_snapshot_with_lineage(snapshot, source, atmospheric_context or {}, observations)
        annotate_snapshot_with_source_summary(snapshot, source_inventory or [], observations)
        route_dir = source_root_dir / route_id
        modules.briefing.write_outputs(
            snapshot,
            output_dir=route_dir,
            question=question,
            location_label=location_label,
            current_time=current_time,
            route=route,
        )
        maybe_generate_route_map(
            modules.map_generator,
            route_dir,
            route,
            snapshot,
            waves_path,
            currents_path,
            skip_maps=skip_maps,
            resolution_label=resolution_label_for(source),
        )
        validate_route_artifacts(route_dir, skip_maps=skip_maps)
        generated_routes[route_id] = route_dir
    return generated_routes


def generate_daily_briefings(
    output_root=DEFAULT_OUTPUT_ROOT,
    run_date=None,
    route_ids=None,
    vessel_class="medium",
    question=None,
    location_label="Palma Marina",
    current_time=None,
    run_id=None,
    skip_maps=False,
    skip_bigquery=False,
    publication_phase="high_resolution",
    wrf_status="complete",
):
    modules = load_mvp_modules()
    run_date = run_date or today_local()
    run_id = run_id or current_run_id_utc()
    current_time = current_time or current_time_local()
    output_root = Path(output_root).resolve()
    day_dir = output_root / run_date
    day_dir.mkdir(parents=True, exist_ok=True)
    run_dir = day_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    selected_route_ids = route_ids_from_args(modules.route_analysis, route_ids)
    routes = modules.route_analysis.load_routes()

    with pushd(HUMANINTHELOOP_DIR):
        observation_bundle = safe_load_observation_bundle(modules.briefing)
        observations = observation_bundle.get("observations", {})
        station_metadata = observation_bundle.get("station_metadata", [])
        try:
            sources = fetch_forecast_sources(modules, run_dir, run_date=run_date)
        except TypeError as error:
            if "run_date" not in str(error):
                raise
            sources = fetch_forecast_sources(modules, run_dir)
        preferred_source = preferred_forecast_source(sources)
        if preferred_source is None:
            preferred_source = cached_forecast_source(modules.fetch_data, run_date=run_date)
            if preferred_source is None:
                raise RuntimeError(
                    "No forecast source available and no cached Copernicus bundle found; "
                    "cannot generate PredSea evidence package."
                )
            sources.append(preferred_source)
        atmospheric_context = fetch_atmospheric_context(modules, run_dir)
        predsea_forecast_bundle = write_predsea_forecast_bundle(
            run_dir,
            run_date,
            run_id,
            preferred_source,
            atmospheric_context,
        )
        forecast_source_entries = source_manifest_entries(modules, sources)
        source_inventory = forecast_source_entries + atmospheric_context.get("atmospheric_sources", [])

        for source in available_forecast_sources(sources):
            source_root_dir = run_dir / "sources" / source["id"]
            generated_routes = generate_route_artifacts_for_source(
                modules,
                source,
                source_root_dir,
                selected_route_ids,
                routes,
                observations,
                vessel_class,
                question,
                location_label,
                current_time,
                skip_maps,
                atmospheric_context=atmospheric_context,
                source_inventory=source_inventory,
            )
            if source["id"] == preferred_source["id"]:
                maybe_generate_leaflet_overlays(run_dir, Path(source["waves_path"]), Path(source["currents_path"]), skip_maps=skip_maps)
                for route_id, source_route_dir in generated_routes.items():
                    copy_preferred_route_artifacts(source_route_dir, run_dir / route_id)

        place_weather_module = getattr(modules, "place_weather", None)
        if place_weather_module is not None:
            place_weather_module.write_place_weather_outputs(
                run_dir,
                run_date,
                run_id,
                preferred_source["waves_path"],
                preferred_source["currents_path"],
                observations=observations,
                station_metadata=station_metadata,
                place_ids=place_weather_module.available_place_ids(),
                time_text=current_time,
            )

        # Persist GMDSS active warnings for the day
        try:
            import gmdss_aggregator
            gmdss_file = run_dir / "active_gmdss_warnings.json"
            gmdss_aggregator.save_warnings_to_file(gmdss_aggregator.MOCK_WARNINGS_DATABASE, filepath=gmdss_file)
            
            # Also save to daily cache file under the output day directory and outputs/ root
            daily_gmdss_file = day_dir / "active_gmdss_warnings.json"
            gmdss_aggregator.save_warnings_to_file(gmdss_aggregator.MOCK_WARNINGS_DATABASE, filepath=daily_gmdss_file)
            
            global_gmdss_file = output_root / "active_gmdss_warnings.json"
            gmdss_aggregator.save_warnings_to_file(gmdss_aggregator.MOCK_WARNINGS_DATABASE, filepath=global_gmdss_file)
            
            print(f"Persisted active GMDSS warnings to run folder, day folder, and global outputs folder.", flush=True)
        except Exception as error:
            print(f"⚠️ Warning: Could not persist GMDSS warnings: {error}", flush=True)

    if atmospheric_context.get("enabled") or atmospheric_context.get("wind_lineage", {}).get("status") != "not_configured":
        forecast_source_entries.append(
            {
                "id": "atmospheric_wind",
                "label": "Tiered atmospheric wind forecast",
                "available": bool(atmospheric_context.get("wind_result", {}).get("available")),
                "preferred": False,
                "metadata": {
                    "wind_lineage": atmospheric_context.get("wind_lineage"),
                    "fetchers_configured": atmospheric_context.get("fetchers_configured", []),
                    "error": atmospheric_context.get("wind_result", {}).get("error"),
                },
            }
    )
    regional_evidence = write_regional_evidence(
        run_dir,
        run_date,
        run_id,
        selected_route_ids,
        forecast_sources=forecast_source_entries,
    )
    regional_manifest_entry = regional_evidence_manifest_entry(regional_evidence)
    preferred_snapshots = load_preferred_snapshots(run_dir, selected_route_ids)
    validation_summary = None
    if hasattr(modules, "validation_archive"):
        validation_summary = modules.validation_archive.write_validation_archive(
            run_dir,
            run_date,
            run_id,
            routes,
            preferred_snapshots,
            observations,
            output_root,
            station_metadata=station_metadata,
            source_inventory=forecast_source_entries + atmospheric_context.get("atmospheric_sources", []),
        )
    validation_entry = validation_manifest_entry(validation_summary)

    # Core publication is the availability boundary. Publish it before
    # optional analytics so BigQuery cannot hide a valid forecast from the API.
    write_manifest(
        run_dir,
        run_date,
        run_id,
        selected_route_ids,
        vessel_class,
        forecast_sources=forecast_source_entries,
        regional_evidence=regional_manifest_entry,
        validation=validation_entry,
        publication_phase=publication_phase,
        wrf_status=wrf_status,
    )
    write_latest_run(
        day_dir,
        run_date,
        run_id,
        selected_route_ids,
        vessel_class,
        regional_evidence=regional_manifest_entry,
        validation=validation_entry,
        publication_phase=publication_phase,
        wrf_status=wrf_status,
    )

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        publish_run_to_gcs(run_dir, day_dir, run_date, run_id)

    if hasattr(modules, "bigquery_export") and not skip_bigquery:
        print("Exporting validation archive to BigQuery...", flush=True)
        bigquery_export_result = modules.bigquery_export.export_validation_archive_to_bigquery(
            run_dir,
            dry_run=False,
        )
        bq_status = bigquery_export_result.get("status")
        bq_obs = bigquery_export_result.get("observation_rows", 0)
        bq_fc = bigquery_export_result.get("forecast_rows", 0)
        bq_exported = bigquery_export_result.get("exported_rows", 0)
        bq_reason = bigquery_export_result.get("reason", "")
        print(
            f"bigquery_export: {bq_status} (obs={bq_obs}, forecast={bq_fc}, exported={bq_exported})"
            + (f" reason={bq_reason}" if bq_reason else ""),
            flush=True,
        )
        write_bigquery_export_diagnostics(run_dir, "bigquery_export", bigquery_export_result)
        if hasattr(modules.bigquery_export, "export_station_metadata_to_bigquery"):
            print("Exporting station metadata to BigQuery...", flush=True)
            station_metadata_export_result = modules.bigquery_export.export_station_metadata_to_bigquery(
                run_dir,
                dry_run=False,
            )
            sm_status = station_metadata_export_result.get("status")
            sm_reason = station_metadata_export_result.get("reason", "")
            print(
                f"station_metadata_export: {sm_status}"
                + (f" reason={sm_reason}" if sm_reason else ""),
                flush=True,
            )
            write_bigquery_export_diagnostics(run_dir, "station_metadata_export", station_metadata_export_result)
        # Upload best-effort export diagnostics. Re-uploading immutable run
        # files and the same latest pointer is idempotent.
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            publish_run_to_gcs(run_dir, day_dir, run_date, run_id)

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            published_sources = publish_latest_copernicus_files(preferred_source, run_date=run_date)
            run_route_precompute(
                waves_path=published_sources.get("waves_path", preferred_source["waves_path"]),
                currents_path=published_sources.get("currents_path", preferred_source["currents_path"]),
                run_date=run_date,
                run_id=run_id,
            )
        except Exception as error:
            print(f"Warning: route precompute skipped or failed; continuing without route cache. {error}", flush=True)

    return SimpleNamespace(output_dir=run_dir, day_dir=day_dir, run_id=run_id, routes=selected_route_ids)


def parse_args():
    parser = argparse.ArgumentParser(description="Generate daily PredSea route briefing artifacts.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--date", dest="run_date", help="Local run date, YYYY-MM-DD. Defaults to Europe/Madrid today.")
    parser.add_argument("--run-id", help="Run identifier. Defaults to current UTC time, e.g. 2026-05-31T0630Z.")
    parser.add_argument("--route", action="append", dest="route_ids", help="Route ID to generate. Repeat for multiple.")
    parser.add_argument("--vessel-class", default="medium", choices=["small", "medium", "large"])
    parser.add_argument("--question", help="Optional captain question to answer for each route snapshot.")
    parser.add_argument("--location-label", default="Palma Marina")
    parser.add_argument("--current-time", help="Local HH:MM for timing-sensitive decision text.")
    parser.add_argument("--skip-maps", action="store_true", help="Do not generate route Decision Map artifacts.")
    parser.add_argument(
        "--skip-bigquery",
        action="store_true",
        help="Publish core forecast artifacts without optional BigQuery exports.",
    )
    parser.add_argument(
        "--publication-phase",
        choices=["preliminary", "high_resolution"],
        default="high_resolution",
        help="Publication phase recorded in run metadata",
    )
    parser.add_argument(
        "--wrf-status",
        choices=["queued", "running", "retrying", "complete", "failed"],
        default="complete",
        help="WRF lifecycle state recorded in run metadata",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    result = generate_daily_briefings(
        output_root=args.output_root,
        run_date=args.run_date,
        route_ids=args.route_ids,
        vessel_class=args.vessel_class,
        question=args.question,
        location_label=args.location_label,
        current_time=args.current_time,
        run_id=args.run_id,
        skip_maps=args.skip_maps,
        skip_bigquery=args.skip_bigquery,
        publication_phase=args.publication_phase,
        wrf_status=args.wrf_status,
    )
    print(f"Wrote PredSea daily briefing artifacts to {result.output_dir}")
    print(f"Run ID: {result.run_id}")
    print(f"Routes: {', '.join(result.routes)}")


if __name__ == "__main__":
    main()
