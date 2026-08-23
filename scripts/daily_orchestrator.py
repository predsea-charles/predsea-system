#!/usr/bin/env python3
"""
PredSea Master Daily Orchestrator.
Unifies boundaries download, GCE Spot VM WRF/ROMS simulation monitoring,
observation ingestion, BigQuery validation logging, and climatology anomaly warnings.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Resolve project paths
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
DEFAULT_FALLBACK_ZONES = ("europe-west1-b", "europe-west1-c", "europe-west1-d")
DEFAULT_FALLBACK_MACHINE_TYPES = (
    "n2-standard-64",
    "n2-standard-32",
    "n2-standard-16",
)
DEFAULT_FORECAST_HOURS = int(os.environ.get("PREDSEA_FORECAST_HOURS", "24"))
DEFAULT_ATMOSPHERIC_SOURCE = os.environ.get(
    "PREDSEA_ATMOSPHERIC_SOURCE", "ecmwf-opendata"
).strip().lower()


def atmospheric_forcing_command(
    source: str,
    *,
    python_bin: str,
    run_date: str,
    forecast_hours: int,
    gcs_bucket: str,
) -> list[str]:
    """Build the selected atmospheric forcing command.

    ECMWF Open Data is the operational default and writes the GRIB2 layout
    consumed directly by WPS. GFS remains an explicit fallback only.
    """
    if source == "ecmwf-opendata":
        return [
            python_bin,
            str(SCRIPTS_DIR / "fetch_ecmwf_forcing.py"),
            f"--run-date={run_date}",
            f"--lead-hours={forecast_hours}",
            f"--gcs-bucket={gcs_bucket}",
            "--skip-if-exists",
        ]
    if source == "gfs":
        return [
            python_bin,
            str(PROJECT_ROOT / "ingestion" / "gfs_puller.py"),
            f"--run-date={run_date}",
        ]
    raise ValueError(f"Unsupported atmospheric source: {source}")


def forecast_resource_defaults(forecast_hours: int) -> tuple[float, str]:
    """Return conservative VM timeout and disk defaults for an hourly WRF horizon."""
    if forecast_hours <= 0:
        raise ValueError("forecast_hours must be positive")
    timeout_hours = max(6.0, (forecast_hours / 24.0) * 4.0)
    disk_gb = max(200, 200 + max(0, forecast_hours - 24) * 3)
    disk_gb = int(math.ceil(disk_gb / 50.0) * 50)
    return round(timeout_hours, 2), f"{disk_gb}GB"


def batch_pipeline_timeout_hours(forecast_hours: int) -> float:
    """Timeout budget for the combined CROCO+SWAN GCP Batch phase, across all
    regions and both models sequentially.

    This used to reuse forecast_resource_defaults()'s WRF-scaled timeout_hours
    (floored at 4.0h), which is wrong: CROCO/SWAN wall-clock time is driven by
    regional grid size and GCP Batch/quota scheduling delays, not by the WRF
    horizon in the same way. Observed in practice: a 6h-forecast run needed
    over 3.5h just for SWAN (after ~30min of CROCO, itself padded by a ~14min
    CPUS_ALL_REGIONS quota wait) across 5 regions, and 3 of them still hadn't
    finished when the old 4.0h ceiling killed the run. This gives the batch
    phase its own, more generous floor plus headroom that scales with horizon.
    """
    if forecast_hours <= 0:
        raise ValueError("forecast_hours must be positive")
    return round(max(8.0, (forecast_hours / 24.0) * 4.0), 2)


def basin_swan_timeout_hours(forecast_hours: int) -> float:
    """Timeout budget for the standalone basin-wide SWAN VM step.

    Must be generous: the full 5-region-union domain is far larger than any
    single region and runs serially on its own VM (see run_basin_swan_step),
    strictly *before* CROCO's Batch jobs are allowed to start (to avoid
    competing for the 64-vCPU CPUS_ALL_REGIONS quota). Observed in practice:
    a 6h-forecast basin-wide SWAN pass at 32 MPI ranks was still running
    after 8+ hours; this floor assumes 64 ranks roughly halves that, with
    real headroom on top since exact scaling hasn't been measured yet.
    """
    if forecast_hours <= 0:
        raise ValueError("forecast_hours must be positive")
    return round(max(12.0, (forecast_hours / 24.0) * 6.0), 2)


def log_step(name: str):
    print("\n" + "=" * 60)
    print(f"👉 [STEP] {name}")
    print("=" * 60)


def run_subprocess(cmd: list[str], dry_run: bool = False) -> int:
    """Run a subprocess with sys.executable and print its output in real-time."""
    print(f"Running: {' '.join(cmd)}")
    if dry_run:
        print("⚡ [DRY RUN] Skipping command execution.")
        return 0

    # Execute in the project root working directory
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(PROJECT_ROOT)
    )

    # Stream output in real-time
    if process.stdout:
        for line in process.stdout:
            print(line, end="")

    return_code = process.wait()
    if return_code != 0:
        print(f"❌ Command failed with return code {return_code}")
    return return_code


def ordered_unique(primary: str, fallbacks: str, defaults: tuple[str, ...]) -> list[str]:
    """Return a stable, de-duplicated CLI fallback sequence."""
    values = [primary]
    values.extend(value.strip() for value in fallbacks.split(",") if value.strip())
    values.extend(defaults)
    return list(dict.fromkeys(values))


def launch_vm_with_fallback(
    base_cmd: list[str],
    zones: list[str],
    machine_types: list[str],
    *,
    dry_run: bool = False,
) -> tuple[str, str, str]:
    """Try reliable regular N2 capacity across zones, then smaller machines."""
    attempts = [
        (zone, machine_type, "STANDARD")
        for machine_type in machine_types
        for zone in zones
    ]
    for attempt_number, (zone, machine_type, provisioning_model) in enumerate(attempts, start=1):
        print(
            f"🚀 VM launch attempt {attempt_number}/{len(attempts)}: "
            f"zone={zone}, machine={machine_type}, model={provisioning_model}"
        )
        cmd = [
            *base_cmd,
            f"--zone={zone}",
            f"--machine-type={machine_type}",
            f"--provisioning-model={provisioning_model}",
        ]
        if run_subprocess(cmd, dry_run=dry_run) == 0:
            print(
                f"✅ VM selected: zone={zone}, machine={machine_type}, "
                f"model={provisioning_model}"
            )
            return zone, machine_type, provisioning_model
        print(f"⚠️ Launch unavailable in {zone} with {machine_type}; trying next fallback.")

    attempted = ", ".join(
        f"{zone}/{machine}/{model}" for zone, machine, model in attempts
    )
    raise RuntimeError(f"VM launch failed for all configured candidates: {attempted}")


def was_instance_preempted(
    instance_name: str,
    zone: str,
    project_id: str,
) -> bool:
    """Return whether Compute Engine recorded a Spot preemption audit event."""
    resource_name = f"projects/{project_id}/zones/{zone}/instances/{instance_name}"
    log_filter = (
        'protoPayload.methodName="compute.instances.preempted" AND '
        f'protoPayload.resourceName="{resource_name}"'
    )
    cmd = [
        "gcloud", "logging", "read", log_filter,
        f"--project={project_id}",
        "--freshness=1h",
        "--limit=1",
        "--format=value(protoPayload.status.message)",
        "--quiet",
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        print(f"⚠️ Unable to check preemption audit log: {error.stderr.strip()}")
        return False
    return "preempted" in result.stdout.lower()


def check_gce_instance_exists(instance_name: str, zone: str, project_id: str | None = None) -> bool:
    """Return whether the GCE workload is still actively running.

    Failed VM startup scripts stop the instance instead of deleting it so its
    disk remains inspectable. Treat TERMINATED as workload completion while
    preserving the resource for diagnostics.
    """
    cmd = [
        "gcloud", "compute", "instances", "describe", instance_name,
        f"--zone={zone}",
        "--format=value(status)"
    ]
    if project_id:
        cmd.append(f"--project={project_id}")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        status = result.stdout.strip()
        print(f"ℹ️ Instance {instance_name} status: {status}")
        return status not in {"TERMINATED", "STOPPING", "SUSPENDED"}
    except subprocess.CalledProcessError as e:
        # If gcloud returns 404 (not found), it's deleted
        if "not found" in e.stderr.lower() or "error" in e.stderr.lower():
            return False
        # Treat other CLI errors as still existing or transient API errors
        print(f"⚠️ Warning: error querying GCE instance: {e.stderr.strip()}")
        return True


def check_gcs_object_exists(gcs_path: str) -> bool:
    """Check if a GCS object exists using gcloud storage objects describe."""
    cmd = ["gcloud", "storage", "objects", "describe", gcs_path, "--format=value(name)"]
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def run_subprocess_capture(cmd: list[str], dry_run: bool = False) -> tuple[int, str]:
    """Like run_subprocess, but also returns the combined stdout/stderr text so
    callers can parse machine-readable lines (e.g. BATCH_JOB_ID=...) out of it."""
    print(f"Running: {' '.join(cmd)}")
    if dry_run:
        print("⚡ [DRY RUN] Skipping command execution.")
        return 0, ""

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(PROJECT_ROOT),
    )
    lines: list[str] = []
    if process.stdout:
        for line in process.stdout:
            print(line, end="")
            lines.append(line)
    return_code = process.wait()
    if return_code != 0:
        print(f"❌ Command failed with return code {return_code}")
    return return_code, "".join(lines)


def get_batch_job_state(job_id: str, location: str, project_id: str | None) -> str | None:
    """Return the live GCP Batch job state (QUEUED/SCHEDULED/RUNNING/SUCCEEDED/
    FAILED), or None if it can't be determined (treated as 'still unknown', not
    as failure)."""
    cmd = [
        "gcloud", "batch", "jobs", "describe", job_id,
        f"--location={location}",
        "--format=value(status.state)",
    ]
    if project_id:
        cmd.append(f"--project={project_id}")
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        state = result.stdout.strip()
        return state or None
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Could not query Batch job state for {job_id}: {e.stderr.strip()}")
        return None

def upload_file_to_gcs(bucket_name: str, local_path: Path, gcs_blob_path: str, dry_run: bool = False) -> None:
    """Upload a local file to GCS, using google-cloud-storage or gsutil fallback."""
    print(f"☁️ Uploading {local_path.name} to gs://{bucket_name}/{gcs_blob_path}...")
    if dry_run:
        print("⚡ [DRY RUN] Skipping upload.")
        return
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_blob_path)
        blob.upload_from_filename(str(local_path))
        print("✅ Uploaded successfully via Python SDK.")
    except Exception as e:
        print(f"⚠️ SDK upload failed: {e}. Trying gsutil fallback...")
        try:
            cmd = ["gsutil", "cp", str(local_path), f"gs://{bucket_name}/{gcs_blob_path}"]
            subprocess.run(cmd, check=True)
            print("✅ Uploaded successfully via gsutil.")
        except Exception as e2:
            print(f"❌ Fallback also failed: {e2}")
            raise


def publish_run_status(
    bucket_name: str,
    run_date: str,
    run_id: str,
    publication_phase: str,
    wrf_status: str,
    message: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Publish lightweight progressive-release status for API consumers."""
    payload = {
        "run_date": run_date,
        "run_id": run_id,
        "publication_phase": publication_phase,
        "wrf_status": wrf_status,
        "message": message,
        "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    print(
        f"📡 Publication status: phase={publication_phase}, wrf={wrf_status} — {message}"
    )
    if dry_run:
        return payload

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    content = json.dumps(payload, indent=2)
    bucket.blob(
        f"predictions/{run_date}/runs/{run_id}/publication_status.json"
    ).upload_from_string(content, content_type="application/json")
    bucket.blob(
        f"predictions/{run_date}/latest_status.json"
    ).upload_from_string(content, content_type="application/json")
    return payload


def delete_gce_instance(instance_name: str, zone: str, project_id: str | None = None):
    """Explicitly delete a GCE instance to avoid runaway costs."""
    print(f"⚠️ Safety Cleanup: Forcing deletion of GCE instance {instance_name} in {zone}...")
    cmd = [
        "gcloud", "compute", "instances", "delete", instance_name,
        f"--zone={zone}",
        "--quiet"
    ]
    if project_id:
        cmd.append(f"--project={project_id}")

    try:
        subprocess.run(cmd, check=True)
        print(f"✅ Instance {instance_name} deleted successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to delete GCE instance {instance_name}: {e.stderr.strip()}")


def run_wrf_step(
    python_bin: str,
    scripts_dir: Path,
    args,
    run_date: str,
    run_id: str,
    zones: list[str],
    machine_types: list[str],
    project_id: str | None,
    notify,
) -> tuple[bool, bool]:
    """Launch the shared WRF Spot VM (confirmed-preemption retries included)
    and poll until it self-terminates with a top-level SUCCESS marker in GCS.

    WRF is always a single run shared by every downstream CROCO/SWAN region,
    never a per-region job. Returns (completed_normally, preliminary_published).
    """
    if args.dry_run:
        print("⚡ [DRY RUN] Simulating WRF VM completion successfully.")
        return True, False

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    instance_name = f"predsea-sim-{run_date.replace('-', '')}-{now_utc.strftime('%H%M%S')}"
    preliminary_published = False
    completed_normally = False
    simulation_attempt = 0

    while simulation_attempt <= args.preemption_retries:
        attempt_instance_name = (
            instance_name
            if simulation_attempt == 0
            else f"{instance_name}-r{simulation_attempt}"
        )
        print(
            f"♻️ WRF VM attempt {simulation_attempt + 1}/"
            f"{args.preemption_retries + 1}; reusing forcing from GCS."
        )
        orchestrator_cmd = [
            python_bin, str(scripts_dir / "gcp_orchestrator.py"),
            f"--instance-name={attempt_instance_name}",
            f"--run-date={run_date}",
            f"--run-id={run_id}",
            f"--gcs-bucket={args.gcs_bucket}",
            f"--image-tag={args.image_tag}",
            f"--boot-disk-size={args.boot_disk_size}",
            f"--forecast-hours={args.forecast_hours}",
        ]
        if args.image_uri:
            orchestrator_cmd.append(f"--image-uri={args.image_uri}")
        if args.project:
            orchestrator_cmd.append(f"--project={args.project}")

        selected_zone, selected_machine_type, provisioning_model = launch_vm_with_fallback(
            orchestrator_cmd,
            zones,
            machine_types,
        )
        if simulation_attempt == 0:
            log_step("2b. Publishing preliminary forecast while WRF runs")
            preliminary_cmd = [
                python_bin, str(scripts_dir / "generate_daily_briefing.py"),
                f"--date={run_date}",
                f"--run-id={run_id}",
                "--publication-phase=preliminary",
                "--wrf-status=running",
                "--skip-maps",
                "--skip-bigquery",
            ]
            preliminary_rc = run_subprocess(preliminary_cmd)
            if preliminary_rc == 0:
                preliminary_published = True
                publish_run_status(
                    args.gcs_bucket,
                    run_date,
                    run_id,
                    "preliminary",
                    "running",
                    "External-source forecast is online; WRF refinement is running.",
                )
            else:
                print(
                    "⚠️ Preliminary publication failed; WRF continues and the final "
                    "publication will still be attempted."
                )
        log_step(
            "3. Polling WRF VM until self-termination "
            f"({provisioning_model}/{selected_machine_type})"
        )
        time.sleep(5)
        start_time = time.time()
        timeout_seconds = args.timeout_hours * 3600

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise RuntimeError(
                    f"WRF simulation timed out after {args.timeout_hours} hours"
                )

            exists = check_gce_instance_exists(
                attempt_instance_name,
                selected_zone,
                args.project,
            )
            if not exists:
                break
            print(
                f"⏳ Still running... Elapsed time: {elapsed/60:.1f} minutes. "
                f"Checking again in {args.poll_interval}s..."
            )
            time.sleep(args.poll_interval)

        success_gcs_path = (
            f"gs://{args.gcs_bucket}/predictions/{run_date}/runs/{run_id}/SUCCESS"
        )
        if check_gcs_object_exists(success_gcs_path):
            print(f"🎉 SUCCESS: WRF completion marker found at {success_gcs_path}.")
            completed_normally = True
            break

        preempted = bool(project_id) and provisioning_model == "SPOT" and was_instance_preempted(
            attempt_instance_name,
            selected_zone,
            project_id,
        )
        if preempted and simulation_attempt < args.preemption_retries:
            simulation_attempt += 1
            if preliminary_published:
                publish_run_status(
                    args.gcs_bucket,
                    run_date,
                    run_id,
                    "preliminary",
                    "retrying",
                    "External-source forecast remains online; WRF was preempted and is retrying.",
                )
            print(
                f"⚠️ Confirmed Spot preemption of {attempt_instance_name}; "
                "launching a replacement VM with the existing GCS inputs."
            )
            continue
        if preempted:
            raise RuntimeError(
                f"WRF simulation exhausted {args.preemption_retries} retries after Spot preemption"
            )
        raise RuntimeError(
            "WRF VM terminated without SUCCESS and was not preempted"
        )

    return completed_normally, preliminary_published


def run_basin_swan_step(
    python_bin: str,
    scripts_dir: Path,
    args,
    run_date: str,
    run_id: str,
    zones: list[str],
    machine_types: list[str],
    project_id: str | None,
) -> bool:
    """Launch a separate, dedicated VM to run the basin-wide SWAN pass (see
    scripts/vm_startup_basin_swan.sh via gcp_orchestrator.py --vm-role=basin-swan),
    only called after run_wrf_step() has confirmed the WRF VM itself finished
    and self-deleted. The two VMs are never up at the same time, so this
    step's 64-vCPU allocation never competes with the WRF VM's -- and, once
    this step returns, CROCO's Batch submissions (main()'s step 2b) can only
    begin once THIS VM has also finished and self-deleted, so it never
    competes with CROCO's Batch jobs either.

    Deliberately non-fatal: CROCO's per-region Batch jobs don't depend on
    basin-wide SWAN's output at all (only 5 already-cropped regional SWAN
    files that get produced as a side effect), so any failure here is logged
    and swallowed rather than raised -- the overall run can still succeed.
    """
    if args.dry_run:
        print("⚡ [DRY RUN] Simulating basin-wide SWAN VM completion successfully.")
        return True

    copernicus_username = os.environ.get("COPERNICUS_USERNAME") or os.environ.get(
        "COPERNICUSMARINE_SERVICE_USERNAME"
    )
    copernicus_password = os.environ.get("COPERNICUS_PASSWORD") or os.environ.get(
        "COPERNICUSMARINE_SERVICE_PASSWORD"
    )
    if not copernicus_username or not copernicus_password:
        print(
            "⚠️ --basin-swan-region is set but COPERNICUS_USERNAME/"
            "COPERNICUS_PASSWORD (or COPERNICUSMARINE_SERVICE_* equivalents) "
            "are not present in this process's environment -- skipping the "
            "basin-wide SWAN pass (non-fatal; CROCO does not depend on it)."
        )
        return False

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    instance_name = f"predsea-swan-{run_date.replace('-', '')}-{now_utc.strftime('%H%M%S')}"
    basin_swan_image_uri = args.basin_swan_image_uri or args.batch_image_uri

    orchestrator_cmd = [
        python_bin, str(scripts_dir / "gcp_orchestrator.py"),
        f"--instance-name={instance_name}",
        f"--run-date={run_date}",
        f"--run-id={run_id}",
        f"--gcs-bucket={args.gcs_bucket}",
        f"--boot-disk-size={args.boot_disk_size}",
        f"--forecast-hours={args.forecast_hours}",
        "--vm-role=basin-swan",
        f"--basin-swan-region={args.basin_swan_region}",
        f"--basin-swan-image-uri={basin_swan_image_uri}",
        f"--basin-swan-mpi-ranks={args.basin_swan_mpi_ranks}",
        f"--copernicus-username={copernicus_username}",
        f"--copernicus-password={copernicus_password}",
    ]
    if args.project:
        orchestrator_cmd.append(f"--project={args.project}")

    try:
        selected_zone, selected_machine_type, provisioning_model = launch_vm_with_fallback(
            orchestrator_cmd,
            zones,
            machine_types,
        )
    except RuntimeError as error:
        print(
            f"⚠️ Basin-wide SWAN VM launch failed: {error}. Continuing -- "
            "CROCO does not depend on this step."
        )
        return False

    log_step(
        "2a-swan. Polling basin-wide SWAN VM until self-termination "
        f"({provisioning_model}/{selected_machine_type})"
    )
    time.sleep(5)
    start_time = time.time()
    timeout_seconds = args.basin_swan_timeout_hours * 3600

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            print(
                f"⚠️ Basin-wide SWAN VM did not finish within "
                f"{args.basin_swan_timeout_hours}h. Continuing -- CROCO does "
                "not depend on this step, but the VM may still be running "
                "and consuming quota; check gcloud compute instances list."
            )
            return False

        exists = check_gce_instance_exists(instance_name, selected_zone, args.project)
        if not exists:
            break
        print(
            f"⏳ Basin-wide SWAN still running... Elapsed time: {elapsed/60:.1f} "
            f"minutes. Checking again in {args.poll_interval}s..."
        )
        time.sleep(args.poll_interval)

    success_gcs_path = (
        f"gs://{args.gcs_bucket}/predictions/{run_date}/runs/{run_id}/BASIN_SWAN_SUCCESS"
    )
    if check_gcs_object_exists(success_gcs_path):
        print(f"🎉 SUCCESS: Basin-wide SWAN completion marker found at {success_gcs_path}.")
        return True

    print(
        "⚠️ Basin-wide SWAN VM terminated without BASIN_SWAN_SUCCESS. "
        "Continuing -- CROCO does not depend on this step."
    )
def run_ww3_sequential_step(
    python_bin: str,
    scripts_dir: Path,
    args,
    run_date: str,
    run_id: str,
) -> bool:
    """Run 48-hour WW3 forecast sequentially over 64-vCPU VMs."""
    log_step("2c. Running WW3 48-hour sequential 64-vCPU forecast pass across all regions")
    if args.dry_run:
        print("⚡ [DRY RUN] Simulating successful WW3 48h sequential forecast pass.")
        return True

    # 1. First, prepare WRF wind forcing for WW3 from WRF d02 outputs
    wrf_dir = Path("outputs") / run_date / "runs" / run_id / "atmosphere"
    if not wrf_dir.exists() or not list(wrf_dir.glob("wrfout_d02_*")):
        wrf_dir.mkdir(parents=True, exist_ok=True)
        gcs_wrf_path = f"gs://{args.gcs_bucket}/predictions/{run_date}/runs/{run_id}/atmosphere/wrfout_d02_*"
        print(f"📥 Downloading WRF d02 outputs from {gcs_wrf_path} to {wrf_dir}...")
        subprocess.run(["gsutil", "-m", "cp", gcs_wrf_path, str(wrf_dir)], check=False)

    wrf_files = list(wrf_dir.glob("wrfout_d02_*"))
    if wrf_files:
        print(f"🍃 Preparing WW3 wind forcing from {len(wrf_files)} WRF d02 files...")
        adapter_cmd = [
            python_bin,
            str(scripts_dir / "prepare_ww3_wind_from_wrf.py"),
            f"--wrf-dir={wrf_dir}",
        ]
        rc = run_subprocess(adapter_cmd)
        if rc == 0:
            gcs_forcing_base = f"gs://{args.gcs_bucket}/scratch/ww3-48h-forcing"
            local_forcing_base = scripts_dir.parent / "simulation" / "marine" / "ww3" / "grids"
            print(f"📤 Uploading WW3 wind forcing from {local_forcing_base} to {gcs_forcing_base}...")
            subprocess.run(["gsutil", "-m", "cp", "-r", f"{local_forcing_base}/*", gcs_forcing_base], check=False)

    # 2. Execute the sequential 64-vCPU script
    script_path = scripts_dir / "submit_ww3_48h_sequential_64cpu.sh"
    if not script_path.exists():
        print(f"⚠️ {script_path} not found; skipping WW3 sequential step.")
        return False

    print(f"🚀 Executing {script_path} for run_date={run_date}...")
    rc = run_subprocess(["bash", str(script_path), run_date])
    return rc == 0


def submit_and_poll_batch_regions(
    python_bin: str,
    scripts_dir: Path,
    model: str,
    active_regions: list[str],
    args,
    run_date: str,
    run_id: str,
    batch_image_uri: str,
    wrf_gcs_uri: str,
    project_id: str | None,
    timeout_seconds: float,
    start_time: float,
    max_concurrent: int,
) -> None:
    """Submit each region's GCP Batch job for `model`, throttled to at most
    `max_concurrent` concurrently in-flight jobs (matching the 64-vCPU
    CPUS_ALL_REGIONS project quota against `--batch-cpu-milli` per
    c2d-highcpu-16 job -- e.g. 64000/16000 = 4), and poll until every region
    reaches its completion marker. As soon as a region completes, a queued
    region is submitted to take its freed slot. Every configured region is
    mandatory: any submission or job failure raises immediately.

    This replaces the old "submit all 5 regions at once, then poll all 5"
    pattern, which submitted 5x16=80 vCPU worth of jobs in one shot --
    already over the 64-vCPU quota on its own, and worse once a separate
    basin-wide SWAN VM might also still be releasing its own 64-vCPU
    allocation around the same time.
    """
    marker_name = "CROCO_SUCCESS" if model == "croco" else "SUCCESS"
    pending = list(active_regions)
    in_flight: dict[str, str] = {}
    completed: set[str] = set()

    CROCO_SPECS = {
        "tyrrhenian_1km": {"machine_type": "n2-custom-24-24576", "cpu_milli": 24000, "memory_mib": 24576, "mpi_ranks": 24},
        "balearic_1km": {"machine_type": "c2d-highcpu-16", "cpu_milli": 16000, "memory_mib": 32768, "mpi_ranks": 16},
        "algerian_1km": {"machine_type": "n2-custom-12-12288", "cpu_milli": 12000, "memory_mib": 12288, "mpi_ranks": 12},
        "alboran_1km": {"machine_type": "c2d-highcpu-8", "cpu_milli": 8000, "memory_mib": 16384, "mpi_ranks": 8},
        "gulf_of_lion_1km": {"machine_type": "c2d-highcpu-4", "cpu_milli": 4000, "memory_mib": 8192, "mpi_ranks": 4},
    }

    def submit_region(region: str) -> None:
        spec = CROCO_SPECS.get(region, {}) if model == "croco" else {}
        m_type = spec.get("machine_type", args.batch_machine_type)
        c_milli = spec.get("cpu_milli", args.batch_cpu_milli)
        mem_mib = spec.get("memory_mib", args.batch_memory_mib)
        ranks = spec.get("mpi_ranks", args.batch_mpi_ranks)

        print(f"\n🚀 Submitting GCP Batch job for region: {region} (model={model}, cpus={c_milli//1000}, machine={m_type})...")
        submit_cmd = [
            python_bin, str(scripts_dir / "submit_gcp_batch_simulation.py"),
            f"--region={region}",
            f"--model={model}",
            f"--forecast-hours={args.forecast_hours}",
            f"--image-uri={batch_image_uri}",
            f"--gcs-bucket={args.gcs_bucket}",
            f"--run-date={run_date}",
            f"--run-id={run_id}",
            f"--timeout-seconds={int(args.batch_timeout_hours * 3600)}",
            f"--wrf-gcs-uri={wrf_gcs_uri}",
            f"--croco-timestep-seconds={args.croco_timestep_seconds}",
            f"--croco-ndtfast={args.croco_ndtfast}",
            f"--machine-type={m_type}",
            f"--cpu-milli={c_milli}",
            f"--memory-mib={mem_mib}",
            f"--mpi-ranks={ranks}",
            f"--provisioning-model={args.batch_provisioning_model}",
        ]
        if project_id:
            submit_cmd.append(f"--project={project_id}")
        if args.dry_run:
            submit_cmd.append("--dry-run")

        rc, output = run_subprocess_capture(submit_cmd, dry_run=args.dry_run)
        if rc != 0:
            raise RuntimeError(
                f"Every configured region is mandatory for model={model}. "
                f"Submission failed for: {region}"
            )
        if args.dry_run:
            in_flight[region] = "dry-run-job-id"
            return
        job_id_match = re.search(r"^BATCH_JOB_ID=(\S+)$", output, re.MULTILINE)
        if not job_id_match:
            raise RuntimeError(
                f"Every configured region is mandatory for model={model}. "
                f"Submission for region {region} exited 0 but no BATCH_JOB_ID "
                "was found in its output"
            )
        in_flight[region] = job_id_match.group(1)

    log_step(
        f"2b. Submitting GCP Batch jobs for model={model} across all regions "
        f"(throttled to {max_concurrent} concurrent, matching the 64-vCPU quota)"
    )
    while pending and len(in_flight) < max_concurrent:
        submit_region(pending.pop(0))

    if args.dry_run:
        print(f"⚡ [DRY RUN] Simulating successful {model} GCS marker discovery for all regions.")
        return

    log_step(f"3. Polling GCP Batch jobs for model={model} (real job state + completion marker)")
    while len(completed) < len(active_regions):
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise RuntimeError(f"GCP Batch multi-region pipeline timed out after {args.batch_timeout_hours} hours")

        print(
            f"\n⏳ {model}: {len(completed)}/{len(active_regions)} complete, "
            f"{len(in_flight)} in flight, {len(pending)} queued. "
            f"Elapsed time: {elapsed/60:.1f} minutes. Checking again in {args.poll_interval}s..."
        )

        for region in list(in_flight.keys()):
            job_id = in_flight[region]
            batch_state = get_batch_job_state(job_id, args.batch_location, project_id)
            if batch_state == "FAILED":
                raise RuntimeError(
                    f"Region '{region}' Batch job {job_id} (model={model}) reported FAILED. "
                    f"Diagnose with: gcloud batch jobs describe {job_id} "
                    f"--location={args.batch_location} --format=json(status)"
                )

            prefix = f"predictions/{run_date}/runs/{run_id}/{region}"
            marker = f"gs://{args.gcs_bucket}/{prefix}/{marker_name}"
            if check_gcs_object_exists(marker):
                print(f"🎉 {model.upper()} SUCCESS: Completed region '{region}'.")
                completed.add(region)
                del in_flight[region]
                if pending:
                    submit_region(pending.pop(0))
            elif batch_state:
                print(f"   {region}: Batch state={batch_state}, {marker_name} marker not yet written")

        if len(completed) < len(active_regions):
            time.sleep(args.poll_interval)

    print(f"\n✅ All regions completed model={model}.")


def main():
    # Resolve project paths and import configuration defaults
    HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
    if str(HUMANINTHELOOP_DIR) not in sys.path:
        sys.path.insert(0, str(HUMANINTHELOOP_DIR))

    try:
        from api.config import PREDSEA_GCS_BUCKET
    except ImportError:
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"

    parser = argparse.ArgumentParser(description="PredSea daily master end-to-end forecasting orchestrator.")
    parser.add_argument("--run-date", help="ISO Run Date YYYY-MM-DD. Defaults to Europe/Madrid today.")
    parser.add_argument("--run-id", help="Run identifier timestamp (defaults to current time)")
    parser.add_argument("--gcs-bucket", default=PREDSEA_GCS_BUCKET, help="Cloud Storage Bucket name")
    parser.add_argument("--zone", default="europe-west1-b", help="GCP Zone")
    parser.add_argument(
        "--batch-location",
        default=os.environ.get("PREDSEA_BATCH_LOCATION", "europe-west1"),
        help="GCP Batch region used for job submission and status polling",
    )
    parser.add_argument(
        "--machine-type",
        default="n2-standard-64",
        help="Primary regular GCP machine type for the simulation VM",
    )
    parser.add_argument(
        "--zones",
        default=",".join(DEFAULT_FALLBACK_ZONES),
        help="Comma-separated zone fallback order",
    )
    parser.add_argument(
        "--machine-types",
        default=",".join(DEFAULT_FALLBACK_MACHINE_TYPES),
        help="Comma-separated machine type fallback order",
    )
    parser.add_argument("--image-tag", default="latest", help="Model Docker image tag (legacy only; use --image-uri)")
    parser.add_argument("--image-uri", default="", help="Immutable WRF image URI containing @sha256:")
    parser.add_argument(
        "--batch-image-uri",
        default=os.environ.get(
            "PREDSEA_BATCH_IMAGE_URI",
            "europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:143e69959c190e0ee912bd4e665919e6ef8ba0c649b747d3618839282af88747"
        ),
        help="Immutable native-model Batch image URI containing @sha256:",
    )
    parser.add_argument(
        "--batch-regions",
        default=os.environ.get(
            "PREDSEA_BATCH_REGIONS",
            "tyrrhenian_1km,balearic_1km,algerian_1km,alboran_1km,gulf_of_lion_1km"
        ),
        help="Comma-separated validated marine regions to submit",
    )
    parser.add_argument(
        "--api-url", default=os.getenv("PREDSEA_API_URL", "http://localhost:8000"), help="Base URL of the FastAPI application"
    )
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud config)")
    parser.add_argument(
        "--use-gcp-batch",
        action="store_true",
        default=os.environ.get("PREDSEA_USE_GCP_BATCH", "1").lower() in ("1", "true"),
        help="Use high-speed multi-region parallel GCP Batch simulations instead of a legacy single-VM"
    )
    parser.add_argument("--dry-run", action="store_true", help="Perform dry-run for boundaries and simulation checks")
    parser.add_argument("--poll-interval", type=int, default=90, help="GCE status polling interval in seconds")
    parser.add_argument(
        "--forecast-hours",
        type=int,
        default=DEFAULT_FORECAST_HOURS,
        help="WRF simulation horizon in hours; forcing coverage must be at least this long",
    )
    parser.add_argument(
        "--atmospheric-source",
        choices=["ecmwf-opendata", "gfs"],
        default=DEFAULT_ATMOSPHERIC_SOURCE,
        help="Atmospheric boundary provider (default: ecmwf-opendata)",
    )
    parser.add_argument(
        "--atmospheric-fallback",
        choices=["gfs", "none"],
        default=os.environ.get("PREDSEA_ATMOSPHERIC_FALLBACK", "gfs").lower(),
        help="Fallback used only if the selected atmospheric source fails",
    )
    parser.add_argument(
        "--timeout-hours",
        type=float,
        help="Maximum execution wait time for the GCE WRF VM; derived from forecast horizon when omitted",
    )
    parser.add_argument(
        "--batch-timeout-hours",
        type=float,
        help=(
            "Maximum wait time for the combined CROCO+SWAN GCP Batch phase "
            "(all regions, both models sequentially), and the per-job GCP "
            "Batch maxRunDuration. Decoupled from --timeout-hours (WRF-only); "
            "derived from forecast horizon when omitted"
        ),
    )
    parser.add_argument(
        "--basin-swan-timeout-hours",
        type=float,
        help=(
            "Maximum wait time for the standalone basin-wide SWAN VM step "
            "(see run_basin_swan_step). Decoupled from --timeout-hours "
            "(WRF-only) and --batch-timeout-hours (CROCO+SWAN Batch phase); "
            "derived from forecast horizon when omitted."
        ),
    )
    parser.add_argument(
        "--boot-disk-size",
        help="Boot disk size for GCE VM; derived from forecast horizon when omitted",
    )
    parser.add_argument(
        "--preemption-retries",
        type=int,
        default=2,
        help="Number of whole-VM retries after confirmed Spot preemption",
    )
    parser.add_argument(
        "--croco-timestep-seconds",
        type=int,
        default=30,
        help="CROCO baroclinic timestep dt (seconds) for Batch regional jobs",
    )
    parser.add_argument(
        "--croco-ndtfast",
        type=int,
        default=45,
        help="CROCO NDTFAST barotropic substeps for Batch regional jobs",
    )
    parser.add_argument(
        "--batch-machine-type",
        default="c2d-highcpu-16",
        help="Machine type for per-region CROCO/SWAN Batch jobs (proven config)",
    )
    parser.add_argument(
        "--batch-cpu-milli",
        type=int,
        default=16000,
        help="CPU millicores for per-region CROCO/SWAN Batch jobs",
    )
    parser.add_argument(
        "--batch-memory-mib",
        type=int,
        default=32768,
        help="Memory MiB for per-region CROCO/SWAN Batch jobs",
    )
    parser.add_argument(
        "--batch-mpi-ranks",
        type=int,
        default=16,
        help="MPI rank count for per-region CROCO/SWAN Batch jobs",
    )
    parser.add_argument(
        "--batch-provisioning-model",
        choices=["SPOT", "STANDARD"],
        default="STANDARD",
        help="Provisioning model for per-region CROCO/SWAN Batch jobs",
    )
    parser.add_argument(
        "--basin-swan-region",
        default="",
        help=(
            "Optional: e.g. med_basin_1km. If set, SWAN runs once over this "
            "basin-wide profile on its own dedicated VM (launched after the "
            "WRF VM finishes and self-deletes, and before CROCO's Batch "
            "jobs are submitted) instead of as 5 separate per-region Batch "
            "jobs -- the per-region SWAN Batch submissions below are "
            "skipped entirely when this is set. CROCO is unaffected and "
            "still runs as 5 regional Batch jobs. Empty by default "
            "(existing behavior)."
        ),
    )
    parser.add_argument(
        "--basin-swan-image-uri",
        default="",
        help="croco-batch image URI for the basin-wide SWAN pass (defaults to --batch-image-uri, since it's the same image).",
    )
    parser.add_argument(
        "--basin-swan-mpi-ranks",
        type=int,
        default=64,
        help="MPI rank count for the basin-wide SWAN pass on its own dedicated VM. Defaults to the full VM (64).",
    )

    args = parser.parse_args()
    if args.forecast_hours <= 0 or args.forecast_hours > 120:
        parser.error("--forecast-hours must be between 1 and 120")
    if args.image_uri and "@sha256:" not in args.image_uri:
        parser.error("--image-uri must be an immutable image digest containing @sha256:")
    default_timeout_hours, default_boot_disk_size = forecast_resource_defaults(args.forecast_hours)
    args.timeout_hours = args.timeout_hours or default_timeout_hours
    args.boot_disk_size = args.boot_disk_size or default_boot_disk_size
    args.batch_timeout_hours = args.batch_timeout_hours or batch_pipeline_timeout_hours(args.forecast_hours)
    args.basin_swan_timeout_hours = args.basin_swan_timeout_hours or basin_swan_timeout_hours(args.forecast_hours)

    # Propagate GOOGLE_CLOUD_PROJECT to sub-processes if explicitly provided
    if args.project:
        os.environ["GOOGLE_CLOUD_PROJECT"] = args.project
    elif not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        # Attempt to auto-detect if not set, to help sub-processes
        try:
            import google.auth
            _, project_id = google.auth.default()
            if project_id:
                os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        except Exception:
            pass

    # Dates calculation matching daily briefing timezone defaults
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    run_date = args.run_date or now_utc.strftime("%Y-%m-%d")
    run_id = args.run_id or now_utc.strftime("%Y-%m-%dT%H%MZ")
    os.environ["PREDSEA_RUN_DATE"] = run_date
    os.environ["PREDSEA_RUN_ID"] = run_id

    # Generate a safe deterministic GCE instance name
    instance_name = f"predsea-sim-{run_date.replace('-', '')}-{now_utc.strftime('%H%M%S')}"

    print("=================================================================")
    print("🌅 PredSea Daily End-to-End Orchestrator Initialized")
    print(f"📅 Run Date: {run_date}")
    print(f"🆔 Run ID: {run_id}")
    print(f"💻 Spot VM Instance Name: {instance_name}")
    print(f"📦 GCS Bucket: {args.gcs_bucket}")
    print(f"📌 Zone: {args.zone} | Machine: {args.machine_type}")
    print(
        f"🕒 Forecast: {args.forecast_hours}h hourly | "
        f"WRF VM timeout: {args.timeout_hours}h | "
        f"Basin-SWAN VM timeout: {args.basin_swan_timeout_hours}h | "
        f"Batch timeout: {args.batch_timeout_hours}h | "
        f"disk: {args.boot_disk_size}"
    )
    print(f"🐳 Image Tag: {args.image_tag}")
    print(f"⚠️ Dry-run: {args.dry_run}")
    print("=================================================================")

    # Define paths to scripts
    python_bin = sys.executable
    notification_script = SCRIPTS_DIR / "notify_status.py"

    def notify(msg: str):
        """Helper to trigger the notification script."""
        n_cmd = [python_bin, str(notification_script), msg]
        if os.getenv("PREDSEA_NOTIFICATION_WEBHOOK"):
            run_subprocess(n_cmd)
        # Always log to stdout for GCP Log-based Alert
        print(f"📢 NOTIFICATION: {msg}")

    preliminary_published = False

    try:
        # Step 1: Download boundaries and upload raw forcing to GCS
        log_step(
            f"1. Fetching boundaries ({args.atmospheric_source} & CMEMS)"
        )

        # Safety: Purge old forcing files to avoid mixing different runs or using corrupted old data
        if not args.dry_run:
            print(f"🧹 Cleaning old forcing files from gs://{args.gcs_bucket}/forcing/ecmwf/{run_date}/...")
            purge_cmd = ["gcloud", "storage", "rm", f"gs://{args.gcs_bucket}/forcing/ecmwf/{run_date}/*.grib2"]
            # We don't fail if this fails (might be empty)
            subprocess.run(purge_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            local_inputs_dir = PROJECT_ROOT / "simulation" / "inputs"
            for stale_path in local_inputs_dir.glob("ecmwf_*.grib2"):
                try:
                    stale_path.unlink()
                    print(f"🧹 Removed local stale forcing file: {stale_path}")
                except FileNotFoundError:
                    pass

        atmospheric_cmd = atmospheric_forcing_command(
            args.atmospheric_source,
            python_bin=python_bin,
            run_date=run_date,
            forecast_hours=args.forecast_hours,
            gcs_bucket=args.gcs_bucket,
        )
        if args.dry_run and args.atmospheric_source == "ecmwf-opendata":
            atmospheric_cmd.append("--dry-run")

        atmospheric_rc = run_subprocess(
            atmospheric_cmd,
            dry_run=args.dry_run and args.atmospheric_source == "gfs",
        )
        if atmospheric_rc != 0:
            if (
                args.atmospheric_fallback == "none"
                or args.atmospheric_source == args.atmospheric_fallback
            ):
                raise RuntimeError(
                    f"Atmospheric boundary download failed ({args.atmospheric_source})"
                )
            print(
                f"⚠️ {args.atmospheric_source} failed; falling back to "
                f"{args.atmospheric_fallback} atmospheric forcing..."
            )
            fallback_cmd = atmospheric_forcing_command(
                args.atmospheric_fallback,
                python_bin=python_bin,
                run_date=run_date,
                forecast_hours=args.forecast_hours,
                gcs_bucket=args.gcs_bucket,
            )
            fallback_rc = run_subprocess(fallback_cmd, dry_run=args.dry_run)
            if fallback_rc != 0:
                raise RuntimeError(
                    "Atmospheric boundary download failed "
                    f"({args.atmospheric_source} & {args.atmospheric_fallback})"
                )

        cmems_cmd = [
            python_bin, str(SCRIPTS_DIR / "fetch_cmems_forcing.py"),
            f"--run-date={run_date}",
            f"--gcs-bucket={args.gcs_bucket}",
            "--skip-if-exists",
        ]
        if args.dry_run:
            cmems_cmd.append("--dry-run")

        cmems_rc = run_subprocess(cmems_cmd)
        if cmems_rc != 0:
            raise RuntimeError("Boundary condition download failed (CMEMS)")

        # Step 1.5: Pre-generate namelist.wps and upload to forcing directory
        log_step("1.5. Pre-generating namelist.wps for simulation run")
        run_date_dt = datetime.datetime.strptime(run_date, "%Y-%m-%d")
        end_date_dt = run_date_dt + datetime.timedelta(hours=args.forecast_hours)
        end_date_str = end_date_dt.strftime("%Y-%m-%d_%H:%M:%S")

        # Create tmp directory in the workspace if it doesn't exist
        tmp_dir = PROJECT_ROOT / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        namelist_local_path = tmp_dir / "namelist.wps"

        setup_domain_cmd = [
            python_bin, str(PROJECT_ROOT / "simulation" / "setup_domain.py"),
            f"--output={namelist_local_path}",
            f"--start-date={run_date}_00:00:00",
            f"--end-date={end_date_str}",
        ]

        setup_rc = run_subprocess(setup_domain_cmd, dry_run=args.dry_run)
        if setup_rc != 0:
            raise RuntimeError("Generating namelist.wps locally failed")

        gcs_namelist_path = f"forcing/ecmwf/{run_date}/namelist.wps"
        upload_file_to_gcs(args.gcs_bucket, namelist_local_path, gcs_namelist_path, dry_run=args.dry_run)

        # Upload modified run_pipeline.sh to avoid expensive docker image rebuilds
        run_pipeline_local_path = PROJECT_ROOT / "simulation" / "run_pipeline.sh"
        gcs_run_pipeline_path = f"forcing/ecmwf/{run_date}/run_pipeline.sh"
        upload_file_to_gcs(args.gcs_bucket, run_pipeline_local_path, gcs_run_pipeline_path, dry_run=args.dry_run)

        # Upload updated setup_domain.py to allow dynamic patching inside the container
        setup_domain_local_path = PROJECT_ROOT / "simulation" / "setup_domain.py"
        gcs_setup_domain_path = f"forcing/ecmwf/{run_date}/setup_domain.py"
        upload_file_to_gcs(args.gcs_bucket, setup_domain_local_path, gcs_setup_domain_path, dry_run=args.dry_run)

        # Upload GRIB2 compatible Vtable to avoid missing Vtable or decoding failures
        vtable_local_path = PROJECT_ROOT / "simulation" / "Vtable.ECMWF_grib2"
        vtable_gcs_path = f"forcing/ecmwf/{run_date}/Vtable.ECMWF_grib2"
        upload_file_to_gcs(args.gcs_bucket, vtable_local_path, vtable_gcs_path, dry_run=args.dry_run)

        # Steps 2-3: launch and monitor the simulation. A confirmed Spot
        # preemption restarts only this section; forcing and configuration are
        # already archived in GCS and are reused by the replacement VM.
        log_step("2. Launching simulation VM")
        zones = ordered_unique(args.zone, args.zones, DEFAULT_FALLBACK_ZONES)
        machine_types = ordered_unique(
            args.machine_type,
            args.machine_types,
            DEFAULT_FALLBACK_MACHINE_TYPES,
        )
        project_id = args.project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        completed_normally = False

        if args.use_gcp_batch:
            log_step("2a. Launching shared WRF Spot VM (all regions read its output)")
            completed_normally, preliminary_published = run_wrf_step(
                python_bin, SCRIPTS_DIR, args, run_date, run_id,
                zones, machine_types, project_id, notify,
            )
            if not completed_normally:
                raise RuntimeError(
                    "WRF did not complete normally; aborting before regional submissions"
                )

            if args.basin_swan_region:
                log_step(
                    "2a-swan. Launching standalone basin-wide SWAN VM "
                    "(only after WRF VM has fully finished and self-deleted)"
                )
                run_basin_swan_step(
                    python_bin, SCRIPTS_DIR, args, run_date, run_id,
                    zones, machine_types, project_id,
                )

            log_step("2b. Submitting Parallel GCP Batch Multi-Region Shards (CROCO + SWAN)")
            regions_dir = PROJECT_ROOT / "simulation" / "marine" / "regions"
            active_regions = [
                value.strip() for value in args.batch_regions.split(",") if value.strip()
            ]
            if not active_regions:
                raise RuntimeError("No --batch-regions were configured")
            missing_profiles = [
                region
                for region in active_regions
                if not (regions_dir / f"{region}.json").exists()
            ]
            if missing_profiles:
                raise RuntimeError(
                    "Unknown Batch region profiles: " + ", ".join(missing_profiles)
                )
            batch_image_uri = args.batch_image_uri
            if not batch_image_uri:
                if args.dry_run:
                    batch_image_uri = "dry-run.invalid/predsea-native@sha256:" + ("0" * 64)
                else:
                    raise RuntimeError(
                        "PREDSEA_BATCH_IMAGE_URI/--batch-image-uri is required"
                    )

            wrf_gcs_uri = f"gs://{args.gcs_bucket}/predictions/{run_date}/runs/{run_id}"
            print(f"Discovered active 1km grids: {', '.join(active_regions)}")
            print(f"Sourcing WRF forcing from this run's own output: {wrf_gcs_uri}")

            # Every configured region is mandatory: a partial submission failure
            # must stop the run rather than silently proceed with fewer regions
            # and later claim "all regions completed successfully."
            #
            # run_marine_simulation.py hard-refuses --model=both (parser.error,
            # exit code 2: "combined execution is intentionally disabled; submit
            # SWAN and CROCO as separate parallel Batch jobs"). So each region
            # gets two independent Batch jobs, one per model.
            #
            # Submitting all 5 regions x 2 models (10 jobs x 16 vCPU = 160 vCPU)
            # at once badly overshoots the 64-vCPU CPUS_ALL_REGIONS project quota.
            # submit_and_poll_batch_regions() throttles each model's phase to at
            # most N_CONCURRENT_BATCH_REGIONS regions in flight at once (64 vCPU
            # / --batch-cpu-milli per job), submitting the next queued region as
            # soon as a slot frees up, rather than submitting all 5 at once.
            timeout_seconds = args.batch_timeout_hours * 3600
            start_time = time.time()
            n_concurrent_batch_regions = max(1, 64000 // args.batch_cpu_milli)

            env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
            wave_model = "swan" if env == "prod" else "ww3"

            # 1. Run CROCO parallel GCP Batch jobs (heterogeneous 64-vCPU split)
            submit_and_poll_batch_regions(
                python_bin, SCRIPTS_DIR, "croco", active_regions, args, run_date, run_id,
                batch_image_uri, wrf_gcs_uri, project_id, timeout_seconds, start_time,
                max_concurrent=n_concurrent_batch_regions,
            )

            # 2. Run Wave Model (SWAN for Prod, WW3 sequential 64-vCPU for Test)
            if wave_model == "swan":
                if not args.basin_swan_region:
                    submit_and_poll_batch_regions(
                        python_bin, SCRIPTS_DIR, "swan", active_regions, args, run_date, run_id,
                        batch_image_uri, wrf_gcs_uri, project_id, timeout_seconds, start_time,
                        max_concurrent=n_concurrent_batch_regions,
                    )
            else:
                run_ww3_sequential_step(python_bin, SCRIPTS_DIR, args, run_date, run_id)

            print(f"\n🏆 All regional jobs (CROCO + {wave_model.upper()}) completed successfully!")
            completed_normally = True

        elif args.dry_run:
            print("⚡ [DRY RUN] Simulating Spot VM completion successfully.")
            completed_normally = True
        else:
            completed_normally, preliminary_published = run_wrf_step(
                python_bin, SCRIPTS_DIR, args, run_date, run_id,
                zones, machine_types, project_id, notify,
            )

        if not completed_normally:
            raise RuntimeError("Simulation did not complete normally")

        if preliminary_published:
            publish_run_status(
                args.gcs_bucket,
                run_date,
                run_id,
                "preliminary",
                "complete",
                "WRF completed; high-resolution artifacts are being published.",
                dry_run=args.dry_run,
            )

        # Step 3b: Ingest high-resolution simulations to BigQuery
        log_step("3b. Ingesting high-resolution simulations to BigQuery")

        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env == "prod":
            ingest_scripts = ["wrf_forecast_ingestor.py", "croco_forecast_ingestor.py", "nemo_forecast_ingestor.py", "swan_forecast_ingestor.py"]
        else:
            ingest_scripts = ["wrf_forecast_ingestor.py", "croco_forecast_ingestor.py", "ww3_forecast_ingestor.py"]

        for ingest_script in ingest_scripts:
            cmd = [
                python_bin, str(SCRIPTS_DIR / ingest_script),
                f"--run-date={run_date}",
                f"--run-id={run_id}",
                f"--gcs-bucket={args.gcs_bucket}",
            ]
            if args.project:
                cmd.append(f"--project={args.project}")
            if args.dry_run:
                cmd.append("--dry-run")

            rc = run_subprocess(cmd)
            if rc != 0:
                print(f"⚠️ Warning: {ingest_script} failed, but continuing pipeline...")

        # Step 4: Observation Ingestion & BigQuery Validation Export
        log_step("4. Observation Ingestion & BigQuery Validation Export")
        briefing_cmd = [
            python_bin, str(SCRIPTS_DIR / "generate_daily_briefing.py"),
            f"--date={run_date}",
            f"--run-id={run_id}",
            "--skip-bigquery",
            "--publication-phase=high_resolution",
            "--wrf-status=complete",
        ]

        briefing_rc = run_subprocess(briefing_cmd, dry_run=args.dry_run)
        if briefing_rc != 0:
            raise RuntimeError("Daily briefing / Ingestion pipeline failed")
        publish_run_status(
            args.gcs_bucket,
            run_date,
            run_id,
            "high_resolution",
            "complete",
            "High-resolution WRF-enhanced forecast is online.",
            dry_run=args.dry_run,
        )

        # Step 5: Execute BigQuery Climatology Anomaly Checker
        log_step("5. BigQuery Climatology Anomaly Check & Warnings Dispatch")
        anomaly_cmd = [
            python_bin, str(SCRIPTS_DIR / "climatology_anomaly_check.py"),
            f"--api-url={args.api_url}",
        ]
        if args.project:
            anomaly_cmd.append(f"--project={args.project}")
        if args.dry_run:
            anomaly_cmd.append("--dry-run")

        anomaly_rc = run_subprocess(anomaly_cmd)
        if anomaly_rc != 0:
            print("⚠️ Warning: Climatology Anomaly Check failed.")

        # Step 6: Real model-vs-observation validation
        log_step("6. Real Model Comparison")
        comparison_cmd = [
            python_bin, str(HUMANINTHELOOP_DIR / "scripts" / "model_comparison.py"),
            f"--date={run_date}",
        ]
        if args.project:
            comparison_cmd.append(f"--project={args.project}")
        comparison_rc = run_subprocess(comparison_cmd, dry_run=args.dry_run)
        if comparison_rc != 0:
            print(
                f"⚠️ Warning: Real Model Comparison step failed (exit code {comparison_rc}). "
                "No accuracy_comparison.json report was produced for this run. "
                "This does not block forecast publication, but it means model quality "
                "is not being measured for this date -- investigate before assuming "
                "validation is happening."
            )
            notify(
                f"⚠️ PredSea Model Comparison Failed: Run {run_date} ({run_id}) published, "
                f"but the accuracy comparison step exited with code {comparison_rc}."
            )

        print("\n🌟 =================================================================")
        print("🏆 PredSea end-to-end daily forecasting orchestrator run successfully!")
        print(f"Run date {run_date} completed successfully.")
        print("=================================================================\n")

        notify(f"✅ PredSea Pipeline Success: Run {run_date} ({run_id}) finished normally.")

    except Exception as e:
        if preliminary_published:
            try:
                publish_run_status(
                    args.gcs_bucket,
                    run_date,
                    run_id,
                    "preliminary",
                    "failed",
                    "External-source forecast remains online; WRF refinement failed.",
                    dry_run=args.dry_run,
                )
            except Exception as status_error:
                print(f"⚠️ Failed to publish terminal forecast status: {status_error}")
        error_msg = f"🚨 PREDSEA_PIPELINE_CRITICAL_FAILURE: {str(e)}"
        print(f"\n{'!'*60}\n{error_msg}\n{'!'*60}\n")
        notify(f"❌ PredSea Pipeline Failure: Run {run_date} failed. Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
