#!/usr/bin/env python3
"""Validate a CROCO grid before promoting it to canonical static storage."""
from __future__ import annotations

import argparse
import re
import os
import subprocess
import tempfile
from pathlib import Path

try:
    from scripts.grid_validation import validate_grid_matches_region
except ModuleNotFoundError:
    from grid_validation import validate_grid_matches_region


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "The only supported pathway for promoting CROCO grids into "
            "static/native-marine. Failure-diagnostics objects are accepted "
            "only after their downloaded content passes regional validation."
        )
    )
    parser.add_argument("--source", required=True, help="Local path, gs:// object, or s3:// object")
    parser.add_argument("--region", required=True, help="Target marine region_id")
    parser.add_argument("--version", required=True, help="Immutable version, e.g. 20260727-v1")
    parser.add_argument("--bucket", required=True, help="Destination bucket name")
    parser.add_argument(
        "--destination-backend", choices=("gcs", "s3"),
        default=os.environ.get("PREDSEA_STORAGE_BACKEND", "gcs"),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the source without writing to GCS",
    )
    return parser.parse_args()


def run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True)


def validate_source(source: str, region_id: str, work_dir: Path) -> Path:
    if source.startswith("gs://"):
        local_grid = work_dir / "croco_grid.nc"
        run_checked(["gsutil", "cp", source, str(local_grid)])
    elif source.startswith("s3://"):
        local_grid = work_dir / "croco_grid.nc"
        run_checked(["aws", "s3", "cp", source, str(local_grid), "--only-show-errors"])
    else:
        local_grid = Path(source).resolve()
        if not local_grid.is_file():
            raise FileNotFoundError(f"CROCO grid source does not exist: {local_grid}")

    validate_grid_matches_region(str(local_grid), region_id)
    return local_grid


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.version):
        raise ValueError(f"invalid immutable version segment: {args.version!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", args.bucket):
        raise ValueError(f"invalid GCS bucket name: {args.bucket!r}")
    with tempfile.TemporaryDirectory(prefix="predsea-grid-promotion-") as tmp:
        local_grid = validate_source(args.source, args.region, Path(tmp))
        print(f"VALIDATED: {local_grid} matches region_id={args.region}")
        if args.validate_only:
            print("VALIDATE_ONLY: no canonical object was written")
            return 0

        scheme = "s3" if args.destination_backend == "s3" else "gs"
        destination = (
            f"{scheme}://{args.bucket}/static/native-marine/{args.region}/"
            f"croco-grid/{args.version}/croco_grid.nc"
        )
        if args.destination_backend == "s3":
            run_checked(["aws", "s3", "cp", str(local_grid), destination, "--sse", "AES256", "--only-show-errors"])
        else:
            run_checked(["gsutil", "cp", str(local_grid), destination])
        print(f"PROMOTED: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
