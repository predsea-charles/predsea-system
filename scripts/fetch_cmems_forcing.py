#!/usr/bin/env python3
"""
PredSea Copernicus Marine (CMEMS) Boundary Conditions Downloader.
Fetches high-resolution daily ocean state data (currents, temperature, salinity, ssh)
from Copernicus Marine Service and uploads to Google Cloud Storage.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

import copernicusmarine

# Load credentials from humanintheloop/.env
BASE_DIR = Path(__file__).resolve().parent.parent
dotenv_path = BASE_DIR / "humanintheloop" / ".env"
load_dotenv(dotenv_path)

# Default dataset IDs for Mediterranean physical states
DEFAULT_PHY_ID = "cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m"
DEFAULT_WAV_ID = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"


def setup_copernicus_auth() -> None:
    """Read credentials from dotenv and map them to copernicusmarine SDK requirements."""
    username = os.getenv("COPERNICUS_USERNAME")
    password = os.getenv("COPERNICUS_PASSWORD")

    if username:
        os.environ["COPERNICUSMARINE_SERVICE_USERNAME"] = username
    if password:
        os.environ["COPERNICUSMARINE_SERVICE_PASSWORD"] = password

    if not os.getenv("COPERNICUS_USERNAME") and not os.getenv("COPERNICUSMARINE_SERVICE_USERNAME"):
        print("WARNING: Copernicus credentials are not set. CMEMS download will fail.", file=sys.stderr)


def upload_to_gcs(bucket_name: str, local_path: Path, gcs_blob_path: str) -> None:
    """Upload a file to Google Cloud Storage."""
    print(f"☁️ Uploading {local_path.name} to gs://{bucket_name}/{gcs_blob_path}...")
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_blob_path)
        blob.upload_from_filename(str(local_path))
        print(f"✅ Uploaded successfully.")
    except Exception as e:
        print(f"⚠️ GCS Upload failed (perhaps local auth is missing or bucket not configured): {e}")


def upload_to_s3(bucket_name: str, local_path: Path, object_key: str) -> None:
    import boto3
    print(f"☁️ Uploading {local_path.name} to s3://{bucket_name}/{object_key}...")
    boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-west-1")).upload_file(
        str(local_path), bucket_name, object_key,
        ExtraArgs={"ServerSideEncryption": "AES256"},
    )


def download_cmems_forcing(
    dataset_id: str,
    variables: list[str] | None,
    output_filename: str,
    output_dir: Path,
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    dry_run: bool = False,
) -> Path:
    """Download subset of CMEMS ocean grids to a local NetCDF file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / output_filename

    print("=============================================")
    print(f"📥 Fetching Copernicus Marine Data")
    print(f"📦 Dataset: {dataset_id}")
    print(f"🧭 Bounding Box: Lon [{lon_min}, {lon_max}] | Lat [{lat_min}, {lat_max}]")
    print(f"⏱️ Time Range: {start_time.isoformat()} to {end_time.isoformat()}")
    print(f"📁 Target: {target_path}")
    print("=============================================")

    if dry_run:
        print("⚡ [DRY RUN] Skipping actual Copernicus API request.")
        return target_path

    # Setup environment auth variables before invoking SDK
    setup_copernicus_auth()

    # Call copernicusmarine subset SDK
    copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=lon_min,
        maximum_longitude=lon_max,
        minimum_latitude=lat_min,
        maximum_latitude=lat_max,
        start_datetime=start_time,
        end_datetime=end_time,
        output_directory=str(output_dir),
        output_filename=output_filename,
        file_format="netcdf",
        overwrite=True,
        dry_run=dry_run,
    )

    if not target_path.exists() or target_path.stat().st_size == 0:
        raise RuntimeError(f"Copernicus Marine download failed or created an empty file: {target_path}")

    print(f"✅ Saved to: {target_path} ({target_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return target_path


def parse_args() -> argparse.Namespace:
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

    parser = argparse.ArgumentParser(description="Download Copernicus Marine ocean boundary/forcing data.")
    parser.add_argument(
        "--dataset-id",
        default=DEFAULT_PHY_ID,
        help="CMEMS dataset ID to download",
    )
    parser.add_argument(
        "--variables",
        nargs="+",
        help="Specific variable names to subset (downloads all if empty)",
    )
    parser.add_argument(
        "--output-filename",
        default="cmems_ocean_forcing.nc",
        help="Output file name",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("simulation/inputs"),
        help="Local output directory",
    )
    parser.add_argument(
        "--lon-min", type=float, default=-6.0, help="Minimum longitude"
    )
    parser.add_argument(
        "--lon-max", type=float, default=15.6, help="Maximum longitude"
    )
    parser.add_argument(
        "--lat-min", type=float, default=35.0, help="Minimum latitude"
    )
    parser.add_argument(
        "--lat-max", type=float, default=44.5, help="Maximum latitude"
    )
    parser.add_argument(
        "--run-date",
        default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        help="Target date YYYY-MM-DD",
    )
    parser.add_argument(
        "--lead-hours",
        type=int,
        default=120,
        help="Forecast lead time in hours (default 120)",
    )
    parser.add_argument(
        "--gcs-bucket",
        default=PREDSEA_GCS_BUCKET,
        help="GCS bucket name for archiving forcing (skips if empty)",
    )
    parser.add_argument("--s3-bucket", default=os.environ.get("PREDSEA_S3_BUCKET"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run without downloading",
    )
    parser.add_argument(
        "--skip-if-exists",
        action="store_true",
        help="Skip download if local file already exists",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Define time window for forcing
    try:
        base_date = datetime.datetime.strptime(args.run_date, "%Y-%m-%d")
    except ValueError:
        print(f"❌ Error: invalid date format '{args.run_date}', must be YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    start_time = base_date.replace(hour=0, minute=0, second=0)
    end_time = start_time + datetime.timedelta(hours=args.lead_hours)

    target_path = Path(args.output_dir) / args.output_filename
    if args.skip_if_exists and target_path.exists() and target_path.stat().st_size > 0:
        print(f"✅ {target_path.name} already exists locally. Skipping download due to --skip-if-exists.")
        path = target_path
    else:
        try:
            path = download_cmems_forcing(
                dataset_id=args.dataset_id,
                variables=args.variables,
                output_filename=args.output_filename,
                output_dir=args.output_dir,
                lon_min=args.lon_min,
                lon_max=args.lon_max,
                lat_min=args.lat_min,
                lat_max=args.lat_max,
                start_time=start_time,
                end_time=end_time,
                dry_run=args.dry_run,
            )
        except Exception as e:
            print(f"❌ CMEMS download failed: {e}", file=sys.stderr)
            sys.exit(1)

    try:

        archive_bucket = args.s3_bucket or args.gcs_bucket
        if archive_bucket and not args.dry_run:
            gcs_path = f"forcing/cmems/{args.run_date}/{path.name}"
            uploader = upload_to_s3 if args.s3_bucket else upload_to_gcs
            uploader(archive_bucket, path, gcs_path)
            print(f"🎉 CMEMS file successfully archived.")

    except Exception as e:
        print(f"❌ CMEMS download process failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
