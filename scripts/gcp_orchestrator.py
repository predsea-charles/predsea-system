#!/usr/bin/env python3
"""
PredSea GCP Spot VM Orchestrator.
Spins up ephemeral Spot VMs to run the WRF/ROMS simulation container.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone


def run_command(cmd: list[str]) -> str:
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"❌ Command failed with exit code {result.returncode}", file=sys.stderr)
        print(f"Stdout:\n{result.stdout}", file=sys.stderr)
        print(f"Stderr:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Command failed: {cmd[0]}")
    return result.stdout.strip()


def get_gcp_project() -> str:
    import os
    # 1. Try environment variables (standard in Google Cloud Run/Build)
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if project:
        return project

    # 2. Try GCP Metadata Server (standard for resources running on GCP)
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"}
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            project_id = response.read().decode("utf-8").strip()
            if project_id:
                return project_id
    except Exception:
        pass

    # 3. Fall back to gcloud config (local development)
    try:
        return run_command(["gcloud", "config", "get-value", "project"])
    except Exception:
        print("❌ Error: Unable to determine active GCP project. Please run 'gcloud config set project [PROJECT]' first.")
        sys.exit(1)



def launch_vm(args):
    project = args.project or get_gcp_project()
    zone = args.zone
    gcs_bucket = args.gcs_bucket
    image_tag = args.image_tag

    now = datetime.now(timezone.utc)
    run_date = args.run_date or now.strftime("%Y-%m-%d")
    run_id = args.run_id or now.strftime("%Y-%m-%dT%H%MZ")

    # Instance naming convention
    instance_name = args.instance_name or f"predsea-sim-{run_date}-{now.strftime('%H%M%S')}"

    print("=============================================")
    import os
    scripts_dir = os.path.dirname(os.path.abspath(__file__))

    # --vm-role selects which of two fully independent VM lifecycles this
    # launch is: "wrf" (default, unchanged WRF-only behavior) or
    # "basin-swan" (a separate VM, launched only after the WRF VM has
    # finished and self-deleted, to run the basin-wide SWAN pass -- see
    # scripts/vm_startup_basin_swan.sh). The two VMs never run at the same
    # time, specifically to avoid both holding a 64-vCPU CPUS_ALL_REGIONS
    # quota allocation simultaneously (which starved CROCO's own per-region
    # Batch job submissions of quota when basin-SWAN used to run alongside
    # WRF on the same reused VM).
    if getattr(args, "vm_role", "wrf") == "basin-swan":
        if not args.basin_swan_region or not args.basin_swan_image_uri:
            print("❌ --vm-role=basin-swan requires --basin-swan-region and --basin-swan-image-uri")
            sys.exit(1)
        if not args.copernicus_username or not args.copernicus_password:
            print(
                "❌ --vm-role=basin-swan requires --copernicus-username and "
                "--copernicus-password (the basin-wide SWAN pass needs "
                "CMEMS wave boundary data)."
            )
            sys.exit(1)
        startup_script = os.path.join(scripts_dir, "vm_startup_basin_swan.sh")
        metadata = (
            f"gcs-bucket={gcs_bucket},run-date={run_date},run-id={run_id},"
            f"forecast-hours={args.forecast_hours},"
            f"basin-swan-region={args.basin_swan_region},"
            f"basin-swan-image-uri={args.basin_swan_image_uri},"
            f"basin-swan-mpi-ranks={args.basin_swan_mpi_ranks},"
            f"copernicus-username={args.copernicus_username},"
            f"copernicus-password={args.copernicus_password}"
        )
    else:
        startup_script = os.path.join(scripts_dir, "vm_startup.sh")
        metadata = (
            f"gcs-bucket={gcs_bucket},run-date={run_date},run-id={run_id},"
            f"image-tag={image_tag},image-uri={getattr(args, 'image_uri', '')},execution-mode={args.execution_mode},"
            f"forecast-hours={getattr(args, 'forecast_hours', 24)}"
        )

    vm_role = getattr(args, "vm_role", "wrf")
    forecast_hrs = getattr(args, "forecast_hours", 24)
    provisioning_model = getattr(args, "provisioning_model", "SPOT").upper()
    print(f"🚀 Preparing to launch {provisioning_model} VM: {instance_name} (role={vm_role})")
    print(f"📍 Zone: {zone}")
    print(f"💻 Machine Type: {args.machine_type}")
    print(f"🪧 Startup Script: {startup_script}")
    print(f"📦 Bucket: {gcs_bucket}")
    print(f"🏷️ Run Date: {run_date} | Run ID: {run_id}")
    print(f"🕒 Forecast horizon: {forecast_hrs} hours")
    print("=============================================")

    # Construct the gcloud compute instances create command
    cmd = [
        "gcloud", "compute", "instances", "create", instance_name,
        f"--project={project}",
        f"--zone={zone}",
        f"--machine-type={args.machine_type}",
        f"--image-family=debian-11",
        f"--image-project=debian-cloud",
        f"--boot-disk-size={args.boot_disk_size}",
        "--subnet=default",
        f"--provisioning-model={provisioning_model}",
        "--scopes=https://www.googleapis.com/auth/cloud-platform",
        f"--metadata-from-file=startup-script={startup_script}",
        f"--metadata={metadata}",
        "--quiet"
    ]
    if provisioning_model == "SPOT":
        cmd.insert(-4, "--instance-termination-action=DELETE")

    try:
        output = run_command(cmd)
        print("✅ Instance successfully requested.")
        print(output)
        print(f"\n💡 Note: The instance will run, upload outputs to gs://{gcs_bucket}/predictions/{run_date}/runs/{run_id}/, and automatically delete itself when finished.")
        print(f"To monitor logs, check Serial Port 1 in the GCP Console, or run:")
        print(f"  gcloud compute instances get-serial-port-output {instance_name} --zone={zone} --project={project}")
    except Exception as e:
        print(f"❌ Failed to launch Spot VM: {e}")
        sys.exit(1)


def main():
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
    if str(HUMANINTHELOOP_DIR) not in sys.path:
        sys.path.insert(0, str(HUMANINTHELOOP_DIR))

    try:
        from api.config import PREDSEA_GCS_BUCKET
    except ImportError:
        import os
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"

    parser = argparse.ArgumentParser(description="Launch ephemeral VMs for high-resolution WRF/ROMS runs.")
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud config)")
    parser.add_argument("--zone", default="europe-west1-b", help="GCP Zone")
    parser.add_argument("--machine-type", default="c2d-standard-56", help="GCP Machine Type (e.g. c2d-standard-56, c2d-standard-32)")
    parser.add_argument("--gcs-bucket", default=PREDSEA_GCS_BUCKET, help="Cloud Storage Bucket name")
    parser.add_argument("--run-date", help="ISO run date YYYY-MM-DD (defaults to today)")
    parser.add_argument("--run-id", help="Run identifier timestamp (defaults to current time)")
    parser.add_argument("--image-tag", default="latest", help="Model Docker image tag (legacy only; use --image-uri)")
    parser.add_argument("--image-uri", default="", help="Immutable WRF image URI containing @sha256:")
    parser.add_argument("--instance-name", help="GCE Instance name (defaults to auto-generated)")
    parser.add_argument("--execution-mode", choices=["container", "bare-metal"], default="container", help="Model execution mode on GCE VM")
    parser.add_argument("--boot-disk-size", default="200GB", help="Boot disk size for GCE VM (e.g. 100GB)")
    parser.add_argument(
        "--forecast-hours",
        type=int,
        default=24,
        help="WRF forecast horizon in hours",
    )
    parser.add_argument(
        "--provisioning-model",
        choices=["SPOT", "STANDARD"],
        default="SPOT",
        help="Use Spot capacity or a regular on-demand VM",
    )
    parser.add_argument(
        "--vm-role",
        choices=["wrf", "basin-swan"],
        default="wrf",
        help=(
            "Which VM lifecycle to launch: 'wrf' (default, unchanged "
            "WRF-only VM) or 'basin-swan' (a separate VM that runs only the "
            "basin-wide SWAN pass; launched by daily_orchestrator.py only "
            "after the WRF VM has fully finished and self-deleted, so the "
            "two never compete for the same 64-vCPU CPUS_ALL_REGIONS quota)."
        ),
    )
    parser.add_argument(
        "--basin-swan-region",
        default="",
        help=(
            "Required if --vm-role=basin-swan (e.g. med_basin_1km): the "
            "region profile to run the basin-wide SWAN pass over."
        ),
    )
    parser.add_argument(
        "--basin-swan-image-uri",
        default="",
        help="croco-batch image URI to use for the basin-wide SWAN pass (required if --vm-role=basin-swan).",
    )
    parser.add_argument(
        "--basin-swan-mpi-ranks",
        type=int,
        default=64,
        help="MPI rank count for the basin-wide SWAN pass. Defaults to the full VM (64) since WRF's own ranks are freed before this step starts.",
    )
    parser.add_argument(
        "--copernicus-username",
        default="",
        help="Copernicus Marine username, required if --basin-swan-region is set.",
    )
    parser.add_argument(
        "--copernicus-password",
        default="",
        help="Copernicus Marine password, required if --basin-swan-region is set.",
    )

    args = parser.parse_args()
    if args.forecast_hours <= 0 or args.forecast_hours > 120:
        parser.error("--forecast-hours must be between 1 and 120")
    if args.image_uri and "@sha256:" not in args.image_uri:
        parser.error("--image-uri must be an immutable image digest containing @sha256:")
    launch_vm(args)


if __name__ == "__main__":
    main()
