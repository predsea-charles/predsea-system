from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


GFS_BUCKET = "noaa-gfs-bdp-pds"
GFS_CYCLES = ("00", "06", "12", "18")
DEFAULT_LOOKBACK_CYCLES = 12
WESTERN_MEDITERRANEAN_BBOX = {
    "min_lon": -6.0,
    "max_lon": 10.0,
    "min_lat": 34.0,
    "max_lat": 45.5,
}


@dataclass(frozen=True)
class GfsPullConfig:
    run_date: datetime
    cycle: str
    output_dir: Path = Path("data/gfs")
    bucket: str = GFS_BUCKET
    bbox: dict[str, float] | None = None

    @property
    def cycle_output_dir(self) -> Path:
        return Path(self.output_dir) / f"gfs.{self.run_date:%Y%m%d}" / self.cycle


def choose_latest_cycle(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    hour = current.astimezone(timezone.utc).hour
    return GFS_CYCLES[hour // 6]


def format_cycle(run_date: datetime, cycle: str) -> str:
    return f"gfs.{run_date:%Y%m%d}/{cycle}/atmos"


def build_s3_prefix(run_date: datetime, cycle: str) -> str:
    return f"{format_cycle(run_date, cycle)}/"


def make_s3_client():
    return boto3.client("s3", config=Config(signature_version=UNSIGNED))


def list_grib_keys(s3_client, config: GfsPullConfig) -> list[str]:
    prefix = build_s3_prefix(config.run_date, config.cycle)
    paginator = s3_client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=config.bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if _is_025_grib2_key(key):
                keys.append(key)
    return sorted(keys)


def _is_025_grib2_key(key: str) -> bool:
    name = key.rsplit("/", 1)[-1]
    return ".pgrb2.0p25." in name and not name.endswith(".idx")


def grib_filter_expression(bbox: dict[str, float] | None = None) -> str:
    bounds = bbox or WESTERN_MEDITERRANEAN_BBOX
    return (
        f"lon>={bounds['min_lon']} && lon<={bounds['max_lon']} && "
        f"lat>={bounds['min_lat']} && lat<={bounds['max_lat']}"
    )


def iter_candidate_cycles(now: datetime, lookback_cycles: int = DEFAULT_LOOKBACK_CYCLES):
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    cycle_hour = (current.hour // 6) * 6
    cycle_time = current.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)

    for offset in range(lookback_cycles):
        candidate = cycle_time - timedelta(hours=6 * offset)
        yield candidate, f"{candidate.hour:02d}"


def find_latest_available_config(
    s3_client,
    now: datetime | None = None,
    output_dir: Path = Path("data/gfs"),
    bucket: str = GFS_BUCKET,
    lookback_cycles: int = DEFAULT_LOOKBACK_CYCLES,
) -> tuple[GfsPullConfig, list[str]]:
    reference_time = now or datetime.now(timezone.utc)
    for run_date, cycle in iter_candidate_cycles(reference_time, lookback_cycles):
        config = GfsPullConfig(run_date=run_date, cycle=cycle, output_dir=output_dir, bucket=bucket)
        keys = list_grib_keys(s3_client, config)
        if keys:
            return config, keys
    raise RuntimeError(f"No GFS 0.25-degree GRIB2 files found in the last {lookback_cycles} cycles.")


def download_latest_cycle(
    output_dir: Path = Path("data/gfs"),
    now: datetime | None = None,
    dry_run: bool = False,
    max_files: int | None = None,
) -> list[Path]:
    s3_client = make_s3_client()
    config, keys = find_latest_available_config(
        s3_client=s3_client,
        now=now,
        output_dir=output_dir,
    )
    selected_keys = keys[:max_files] if max_files else keys

    if dry_run:
        for key in selected_keys:
            print(key)
        return []

    ensure_wgrib2_available()
    config.cycle_output_dir.mkdir(parents=True, exist_ok=True)
    return [_download_and_filter(s3_client, config, key) for key in selected_keys]


@retry(
    retry=retry_if_exception_type((OSError, subprocess.SubprocessError)),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _download_and_filter(s3_client, config: GfsPullConfig, key: str) -> Path:
    raw_path = config.cycle_output_dir / Path(key).name
    filtered_path = raw_path.with_suffix(raw_path.suffix + ".westmed.grib2")
    s3_client.download_file(config.bucket, key, str(raw_path))
    filter_grib_to_bbox(raw_path, filtered_path, config.bbox or WESTERN_MEDITERRANEAN_BBOX)
    return filtered_path


def filter_grib_to_bbox(input_path: Path, output_path: Path, bbox: dict[str, float]) -> None:
    """Filter a GRIB2 file to the Western Med if wgrib2 is installed.

    GFS public S3 objects are full global GRIB2 files. The efficient operational
    path is to fetch the GRIB object and immediately reduce it with `wgrib2`.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "wgrib2",
        str(input_path),
        "-small_grib",
        f"{bbox['min_lon']}:{bbox['max_lon']}",
        f"{bbox['min_lat']}:{bbox['max_lat']}",
        str(output_path),
    ]
    subprocess.run(command, check=True)


def ensure_wgrib2_available() -> None:
    if shutil.which("wgrib2") is None:
        raise RuntimeError(
            "wgrib2 is required for Phase 3 GRIB2 bounding-box filtering. "
            "Install it first, for example with `conda install -c conda-forge wgrib2` "
            "or run inside an image that includes wgrib2."
        )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull latest NOAA GFS 0.25-degree GRIB2 cycle.")
    parser.add_argument("--output-dir", type=Path, default=Path("data/gfs"))
    parser.add_argument("--dry-run", action="store_true", help="List matching S3 keys without downloading.")
    parser.add_argument("--max-files", type=int, default=None, help="Limit files for smoke tests.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    paths = download_latest_cycle(
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        max_files=args.max_files,
    )
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
