#!/usr/bin/env python3
"""Crop a basin-wide SWAN forecast NetCDF into the 5 per-region files the rest
of the pipeline (swan_forecast_ingestor.py, validate_marine_output.py,
downstream product/API code) already expects.

Context: med_basin_1km.json runs SWAN once over the union bbox of
alboran_1km, gulf_of_lion_1km, balearic_1km, tyrrhenian_1km, and
algerian_1km, instead of 5 separate small-domain jobs (3 of which currently
fail or misbehave under SWAN's fixed-rank MPI decomposition on narrow/
elongated coastlines). run_marine_simulation.py + vtk_to_netcdf.py already
produce a canonical `med_basin_1km_swan_forecast.nc` unmodified (they derive
the output filename purely from --region, so no changes were needed there).
This script is the one new piece required: slicing that single file back
into 5 region-scoped files with the exact same name/variable/coordinate
schema (significant_wave_height, peak_wave_period, mean_wave_direction,
depth over time/latitude/longitude) so nothing downstream has to change.

Usage:
    # Local-only (crop files on disk, e.g. to inspect before uploading):
    .venv/bin/python3 scripts/crop_basin_swan_output.py \\
        --basin-file ./med_basin_1km_swan_forecast.nc \\
        --output-dir ./cropped

    # Crop and upload each region's file to the same GCS layout a per-region
    # SWAN Batch job would have used (predictions/{run_date}/runs/{run_id}/{region}/{region}_swan_forecast.nc):
    .venv/bin/python3 scripts/crop_basin_swan_output.py \\
        --basin-file ./med_basin_1km_swan_forecast.nc \\
        --output-dir ./cropped \\
        --gcs-bucket predsea-daily-outputs-test --run-date 2026-07-30 --run-id 2026-07-30T0600Z
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import xarray as xr

REGIONS_DIR = Path(__file__).resolve().parents[1] / "simulation" / "marine" / "regions"

# The 5 regions med_basin_1km.json's bbox is a union of. Kept as an explicit
# list (rather than "every profile with models_enabled excluding med_basin
# itself") so this script fails loudly if a region file goes missing, instead
# of silently cropping whatever happens to be in the directory.
DEFAULT_TARGET_REGIONS = (
    "alboran_1km",
    "gulf_of_lion_1km",
    "balearic_1km",
    "tyrrhenian_1km",
    "algerian_1km",
)


def _load_region_bbox(region_id: str) -> dict:
    path = REGIONS_DIR / f"{region_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown region profile: {path}")
    region = json.loads(path.read_text())
    return region["bbox"]


def crop_region(basin_ds: xr.Dataset, bbox: dict) -> xr.Dataset:
    """Slice the basin-wide dataset to one region's bbox.

    vtk_to_netcdf.py builds latitude/longitude as ascending 1D coordinate
    arrays (CGRID's lower-left origin plus the "coordinates must increase
    west-east and south-north" invariant enforced in prepare_swan_run.py), so
    a plain ascending .sel(slice(min, max)) is valid -- no sort/reverse
    handling needed.
    """
    cropped = basin_ds.sel(
        longitude=slice(bbox["longitude_min"], bbox["longitude_max"]),
        latitude=slice(bbox["latitude_min"], bbox["latitude_max"]),
    )
    if cropped.sizes.get("longitude", 0) == 0 or cropped.sizes.get("latitude", 0) == 0:
        raise ValueError(
            f"Cropping to bbox {bbox} produced an empty slice -- the basin "
            "file's coverage does not actually include this region. Check "
            "that med_basin_1km.json's bbox still covers every target "
            "region (it must be a superset, not just an overlapping box)."
        )
    return cropped


def upload_to_gcs(local_path: Path, bucket_name: str, run_date: str, run_id: str, region_id: str) -> str:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob_path = f"predictions/{run_date}/runs/{run_id}/{region_id}/{region_id}_swan_forecast.nc"
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(str(local_path))
    gcs_uri = f"gs://{bucket_name}/{blob_path}"
    print(f"☁️  Uploaded {local_path.name} -> {gcs_uri}")
    return gcs_uri


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basin-file", type=Path, required=True, help="Path to the basin-wide *_swan_forecast.nc file (e.g. med_basin_1km_swan_forecast.nc).")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to write the 5 cropped {region}_swan_forecast.nc files into.")
    parser.add_argument(
        "--regions",
        default=",".join(DEFAULT_TARGET_REGIONS),
        help="Comma-separated region IDs to crop out of the basin file (default: the 5 regions med_basin_1km.json unions).",
    )
    parser.add_argument("--gcs-bucket", help="If set, upload each cropped file to this bucket using the same layout a per-region SWAN Batch job would have used.")
    parser.add_argument("--run-date", help="Required if --gcs-bucket is set.")
    parser.add_argument("--run-id", help="Required if --gcs-bucket is set.")
    args = parser.parse_args()
    if args.gcs_bucket and not (args.run_date and args.run_id):
        parser.error("--gcs-bucket requires --run-date and --run-id")
    return args


def main() -> int:
    args = parse_args()
    target_regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    if not target_regions:
        raise SystemExit("--regions produced an empty list")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(args.basin_file) as basin_ds:
        basin_lon_span = (float(basin_ds["longitude"].min()), float(basin_ds["longitude"].max()))
        basin_lat_span = (float(basin_ds["latitude"].min()), float(basin_ds["latitude"].max()))
        print(
            f"Basin file coverage: longitude {basin_lon_span[0]:.3f}..{basin_lon_span[1]:.3f}, "
            f"latitude {basin_lat_span[0]:.3f}..{basin_lat_span[1]:.3f}"
        )

        results = {}
        for region_id in target_regions:
            bbox = _load_region_bbox(region_id)
            print(f"\n🔪 Cropping {region_id} (bbox lon {bbox['longitude_min']}..{bbox['longitude_max']}, "
                  f"lat {bbox['latitude_min']}..{bbox['latitude_max']})...")
            cropped = crop_region(basin_ds, bbox)
            out_path = args.output_dir / f"{region_id}_swan_forecast.nc"
            cropped.to_netcdf(out_path, format="NETCDF4")
            print(f"✅ Wrote {out_path} ({cropped.sizes['longitude']}x{cropped.sizes['latitude']} grid, "
                  f"{cropped.sizes.get('time', 1)} timesteps)")

            gcs_uri = None
            if args.gcs_bucket:
                gcs_uri = upload_to_gcs(out_path, args.gcs_bucket, args.run_date, args.run_id, region_id)
            results[region_id] = {
                "local_path": str(out_path),
                "grid": {"nx": cropped.sizes["longitude"], "ny": cropped.sizes["latitude"]},
                "timesteps": cropped.sizes.get("time", 1),
                "gcs_uri": gcs_uri,
            }

    print("\n" + json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
