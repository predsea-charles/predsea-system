#!/usr/bin/env python3
"""Fetch the explicit CMEMS inputs required by native SWAN and CROCO runs."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
import copernicusmarine
import numpy as np
import xarray as xr

try:
    from scripts.validate_marine_region import validate_region
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from validate_marine_region import validate_region


DATASETS = {
    "croco_currents_3d": {
        "dataset_id": "cmems_mod_med_phy-cur_anfc_4.2km-3D_PT1H-m",
        "variables": ["uo", "vo"],
        "filename": "cmems_croco_currents_3d.nc",
        "required": ["uo", "vo", "depth", "time"],
    },
    "croco_temperature_3d": {
        "dataset_id": "cmems_mod_med_phy-tem_anfc_4.2km-3D_PT1H-m",
        "variables": ["thetao"],
        "filename": "cmems_croco_temperature_3d.nc",
        "required": ["thetao", "depth", "time"],
    },
    "croco_salinity_3d": {
        "dataset_id": "cmems_mod_med_phy-sal_anfc_4.2km-3D_PT1H-m",
        "variables": ["so"],
        "filename": "cmems_croco_salinity_3d.nc",
        "required": ["so", "depth", "time"],
    },
    "croco_sea_level": {
        "dataset_id": "cmems_mod_med_phy-ssh_anfc_4.2km-2D_PT1H-m",
        "variables": ["zos"],
        "filename": "cmems_croco_sea_level.nc",
        "required": ["zos", "time"],
    },
    "swan_boundary": {
        "dataset_id": "cmems_mod_med_wav_anfc_4.2km_PT1H-i",
        "variables": ["VHM0", "VMDR", "VTPK"],
        "filename": "cmems_swan_boundary.nc",
        "required": ["VHM0", "VMDR", "VTPK", "time"],
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_file(
    path: Path,
    required: list[str],
    expected_timestamps: int,
    expected_start: dt.datetime | None = None,
    expected_end: dt.datetime | None = None,
) -> dict:
    errors: list[str] = []
    with xr.open_dataset(path) as dataset:
        names = set(dataset.variables) | set(dataset.dims)
        missing = sorted(set(required) - names)
        if missing:
            errors.append(f"missing fields/dimensions: {', '.join(missing)}")
        timestamp_count = int(dataset.sizes.get("time", 0))
        if timestamp_count != expected_timestamps:
            errors.append(
                f"expected {expected_timestamps} timestamps, found {timestamp_count}"
            )
        actual_start = None
        actual_end = None
        if "time" in dataset.variables and timestamp_count:
            timestamps = dataset["time"].values.astype("datetime64[s]")
            actual_start = str(timestamps[0])
            actual_end = str(timestamps[-1])
            if expected_start is not None:
                wanted = np.datetime64(expected_start.replace(tzinfo=None), "s")
                if timestamps[0] != wanted:
                    errors.append(
                        f"expected first timestamp {wanted}, found {timestamps[0]}"
                    )
            if expected_end is not None:
                wanted = np.datetime64(expected_end.replace(tzinfo=None), "s")
                if timestamps[-1] != wanted:
                    errors.append(
                        f"expected last timestamp {wanted}, found {timestamps[-1]}"
                    )
        depth_count = int(dataset.sizes.get("depth", 0))
        sizes = {name: int(value) for name, value in dataset.sizes.items()}
    return {
        "status": "succeeded" if not errors else "failed",
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
        "sizes": sizes,
        "timestamp_count": timestamp_count,
        "first_timestamp": actual_start,
        "last_timestamp": actual_end,
        "depth_count": depth_count,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--forecast-hours", type=int, default=6)
    parser.add_argument(
        "--region",
        type=Path,
        default=Path("simulation/marine/regions/balearic_1km.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models", nargs="+", choices=("swan", "croco"), default=["swan", "croco"])
    parser.add_argument("--maximum-depth", type=float, default=6000.0)
    parser.add_argument(
        "--dotenv",
        type=Path,
        help="Optional credentials file outside the source/build context.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dotenv_path = args.dotenv or (
        Path(__file__).resolve().parents[1] / "humanintheloop" / ".env"
    )
    load_dotenv(dotenv_path)
    username = os.getenv("COPERNICUS_USERNAME") or os.getenv(
        "COPERNICUSMARINE_SERVICE_USERNAME"
    )
    password = os.getenv("COPERNICUS_PASSWORD") or os.getenv(
        "COPERNICUSMARINE_SERVICE_PASSWORD"
    )
    if username:
        os.environ["COPERNICUSMARINE_SERVICE_USERNAME"] = username
    if password:
        os.environ["COPERNICUSMARINE_SERVICE_PASSWORD"] = password
    if not args.dry_run and (not username or not password):
        raise SystemExit("Copernicus Marine credentials are not configured")

    region_validation = validate_region(args.region)
    if region_validation["status"] != "succeeded":
        raise SystemExit(
            "Marine region profile failed preflight: "
            + "; ".join(region_validation["errors"])
        )
    region = json.loads(args.region.read_text())
    bbox = region["bbox"]
    # Copernicus interprets naive datetimes in the host timezone. Always send
    # UTC-aware bounds so staging runs are not silently shifted by Madrid DST.
    start = dt.datetime.strptime(args.run_date, "%Y-%m-%d").replace(
        tzinfo=dt.timezone.utc
    )
    end = start + dt.timedelta(hours=args.forecast_hours)
    expected_timestamps = args.forecast_hours + 1
    selected = []
    if "croco" in args.models:
        selected.extend(
            (
                "croco_currents_3d",
                "croco_temperature_3d",
                "croco_salinity_3d",
                "croco_sea_level",
            )
        )
    if "swan" in args.models:
        selected.append("swan_boundary")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    products: dict[str, dict] = {}
    for product_name in selected:
        spec = DATASETS[product_name]
        target = args.output_dir / spec["filename"]
        if args.dry_run:
            products[product_name] = {
                "status": "planned",
                "dataset_id": spec["dataset_id"],
                "variables": spec["variables"],
                "path": str(target),
            }
        if not target.exists() or args.overwrite:
            buffer = 0.5
            kwargs = {
                "dataset_id": spec["dataset_id"],
                "username": username,
                "password": password,
                "variables": spec["variables"],
                "minimum_longitude": bbox["longitude_min"] - buffer,
                "maximum_longitude": bbox["longitude_max"] + buffer,
                "minimum_latitude": bbox["latitude_min"] - buffer,
                "maximum_latitude": bbox["latitude_max"] + buffer,
                "start_datetime": start,
                "end_datetime": end,
                "output_directory": str(args.output_dir),
                "output_filename": spec["filename"],
                "file_format": "netcdf",
                "overwrite": True,
            }
            if "_3d" in product_name:
                kwargs["minimum_depth"] = 0.0
                kwargs["maximum_depth"] = args.maximum_depth
            copernicusmarine.subset(**kwargs)
        validation = validate_file(
            target,
            spec["required"],
            expected_timestamps,
            expected_start=start,
            expected_end=end,
        )
        products[product_name] = {
            "dataset_id": spec["dataset_id"],
            "variables": spec["variables"],
            **validation,
        }

    failed = [
        name
        for name, product in products.items()
        if product["status"] not in ("succeeded", "planned")
    ]
    manifest = {
        "schema_version": "predsea.native_marine_forcing.v1",
        "status": "failed" if failed else ("planned" if args.dry_run else "succeeded"),
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run_date": args.run_date,
        "forecast_hours": args.forecast_hours,
        "region_id": region["region_id"],
        "bbox": bbox,
        "models": args.models,
        "products": products,
        "errors": [f"{name} failed validation" for name in failed],
    }
    manifest_path = args.output_dir / "forcing_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
