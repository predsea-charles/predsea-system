#!/usr/bin/env python3
"""
PredSea Bathymetry Preparation Utility.
Downloads raw bathymetry from EMODnet Bathymetry Web Coverage Service (WCS) as GeoTIFF,
crops and regrids it to the target SWAN computational domain coordinates,
and uploads the finalized NetCDFs to Google Cloud Storage.

This utility automatically handles large regions by using spatial tiling and stitching
to bypass the EMODnet WCS server download limits.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import numpy as np
import scipy.interpolate as interp
import xarray as xr
import requests
from PIL import Image

# Resolve project paths
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
REGIONS_DIR = PROJECT_ROOT / "simulation" / "marine" / "regions"


def load_region_bbox(region_id: str) -> tuple[float, float, float, float, float]:
    """Read a region's bbox + resolution from its committed JSON profile.

    Returns (lon_min, lon_max, lat_min, lat_max, resolution_deg). Resolution is
    derived from horizontal_resolution_m (meters) using the same ~111km/degree
    approximation used elsewhere in this codebase (submit_gcp_batch_simulation.py).
    """
    profile_path = REGIONS_DIR / f"{region_id}.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"No region profile found at {profile_path}")
    profile = json.loads(profile_path.read_text())
    bbox = profile["bbox"]
    resolution_deg = profile["horizontal_resolution_m"] / 111_000.0
    return (
        bbox["longitude_min"],
        bbox["longitude_max"],
        bbox["latitude_min"],
        bbox["latitude_max"],
        resolution_deg,
    )


def download_emodnet_bathymetry(
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    output_path: Path,
    dry_run: bool = False,
    resx: str = "0.00104166",
    resy: str = "0.00104166",
) -> bool:
    """Download a subset of EMODnet Bathymetry as GeoTIFF using Web Coverage Service (WCS)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # EMODnet WCS 1.0.0 GetCoverage URL
    wcs_url = "https://ows.emodnet-bathymetry.eu/wcs"
    
    # Coordinates bounding box in EPSG:4326: min_lon,min_lat,max_lon,max_lat
    bbox_str = f"{lon_min},{lat_min},{lon_max},{lat_max}"
    
    params = {
        "service": "WCS",
        "version": "1.0.0",
        "request": "GetCoverage",
        "coverage": "emodnet:mean",
        "crs": "EPSG:4326",
        "bbox": bbox_str,
        "format": "GeoTIFF",
        "resx": resx,
        "resy": resy,
    }
    
    print("=============================================")
    print("📥 Requesting Bathymetry from EMODnet WCS as GeoTIFF")
    print(f"🧭 Bounding Box: Lon [{lon_min:.4f}, {lon_max:.4f}] | Lat [{lat_min:.4f}, {lat_max:.4f}]")
    print(f"📏 Resolution: {resx} degrees")
    print(f"📁 Local Target: {output_path}")
    print("=============================================")
    
    if dry_run:
        print("⚡ [DRY RUN] Skipping actual EMODnet WCS download.")
        return True
        
    try:
        response = requests.get(wcs_url, params=params, timeout=180, stream=True)
        if response.status_code != 200:
            print(f"❌ EMODnet WCS returned status code {response.status_code}")
            print(response.text[:500])
            return False
            
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    
        print(f"✅ Successfully downloaded raw bathymetry ({output_path.stat().st_size / 1024 / 1024:.2f} MB)")
        return True
    except Exception as e:
        print(f"❌ Failed to download EMODnet bathymetry: {e}")
        return False


def upload_to_gcs(bucket_name: str, local_path: Path, gcs_blob_path: str) -> None:
    """Upload a file to Google Cloud Storage."""
    print(f"☁️ Uploading {local_path.name} to gs://{bucket_name}/{gcs_blob_path}...")
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_blob_path)
        blob.upload_from_filename(str(local_path))
        print("✅ Uploaded successfully.")
    except Exception as e:
        print(f"⚠️ GCS Upload failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Prepare bathymetry for the SWAN model.")
    parser.add_argument(
        "--region",
        help=(
            "Region ID (e.g., balearic_1km, alboran_1km). When set, the bbox "
            "and resolution are read from simulation/marine/regions/{region}.json "
            "and --lon-min/--lon-max/--lat-min/--lat-max/--resolution are ignored."
        ),
    )
    parser.add_argument("--lon-min", type=float, default=1.0, help="Minimum longitude (ignored if --region is set)")
    parser.add_argument("--lon-max", type=float, default=5.0, help="Maximum longitude (ignored if --region is set)")
    parser.add_argument("--lat-min", type=float, default=38.0, help="Minimum latitude (ignored if --region is set)")
    parser.add_argument("--lat-max", type=float, default=41.0, help="Maximum latitude (ignored if --region is set)")
    parser.add_argument("--resolution", type=float, default=0.01, help="Grid spacing in degrees (0.01 = ~1km); ignored if --region is set")
    parser.add_argument("--gcs-bucket", default="predsea-daily-outputs", help="GCS Bucket name")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (defaults to simulation/inputs).",
    )
    parser.add_argument("--no-upload", action="store_true", help="Do not upload generated grids.")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run")
    args = parser.parse_args()

    if args.region:
        args.lon_min, args.lon_max, args.lat_min, args.lat_max, args.resolution = load_region_bbox(args.region)
        print(f"📐 Loaded bbox/resolution for region '{args.region}' from its profile: "
              f"lon [{args.lon_min}, {args.lon_max}], lat [{args.lat_min}, {args.lat_max}], "
              f"resolution {args.resolution:.6f} deg")

    file_prefix = args.region if args.region else "balearic_1km"
    input_dir = args.output_dir or (PROJECT_ROOT / "simulation" / "inputs")
    input_dir.mkdir(parents=True, exist_ok=True)
    swan_path = input_dir / f"{file_prefix}_bathymetry_swan.nc"

    width_deg = args.lon_max - args.lon_min
    height_deg = args.lat_max - args.lat_min
    area = width_deg * height_deg
    
    # We define target regular grids upfront
    target_lons = np.arange(args.lon_min, args.lon_max + args.resolution, args.resolution)
    target_lats = np.arange(args.lat_min, args.lat_max + args.resolution, args.resolution)
    lon_mesh, lat_mesh = np.meshgrid(target_lons, target_lats)
    
    master_depth = np.zeros((len(target_lats), len(target_lons)), dtype=np.float32)
    master_mask = np.zeros((len(target_lats), len(target_lons)), dtype=bool)
    
    # Use tiling if the area is large (e.g. > 16 square degrees) to avoid EMODnet WCS server size limits
    if area > 16.0:
        print("🧱 Large bounding box detected! Utilizing spatial tiling to bypass EMODnet limits.")
        # Divide into smaller tiles of ~3.0 degrees
        tile_size = 3.0
        lon_steps = int(np.ceil(width_deg / tile_size))
        lat_steps = int(np.ceil(height_deg / tile_size))
        
        lon_edges = np.linspace(args.lon_min, args.lon_max, lon_steps + 1)
        lat_edges = np.linspace(args.lat_min, args.lat_max, lat_steps + 1)
        
        print(f"📦 Splitting region into a {lon_steps}x{lat_steps} grid ({lon_steps * lat_steps} total tiles)...")
        
        for i in range(lon_steps):
            for j in range(lat_steps):
                print(f"\n--- 🧩 Processing Tile (Lon step {i+1}/{lon_steps}, Lat step {j+1}/{lat_steps}) ---")
                # Add small overlap buffer of 0.05 degrees to prevent interpolation edge gaps
                pad = 0.05
                tile_lon_min = max(args.lon_min, lon_edges[i] - pad)
                tile_lon_max = min(args.lon_max, lon_edges[i+1] + pad)
                tile_lat_min = max(args.lat_min, lat_edges[j] - pad)
                tile_lat_max = min(args.lat_max, lat_edges[j+1] + pad)
                
                # Dynamic resolution for this tile
                tile_width = tile_lon_max - tile_lon_min
                tile_height = tile_lat_max - tile_lat_min
                res_val = max(0.00104166, args.resolution / 2.0)
                tile_max_deg = max(tile_width, tile_height)
                if tile_max_deg / res_val > 4000:
                    res_val = tile_max_deg / 4000.0
                    
                resx_str = f"{res_val:.8f}"
                resy_str = f"{res_val:.8f}"
                
                tile_raw_path = input_dir / f"emodnet_bathymetry_tile_{i}_{j}.tiff"
                
                success = download_emodnet_bathymetry(
                    lon_min=tile_lon_min,
                    lon_max=tile_lon_max,
                    lat_min=tile_lat_min,
                    lat_max=tile_lat_max,
                    output_path=tile_raw_path,
                    dry_run=args.dry_run,
                    resx=resx_str,
                    resy=resy_str,
                )
                
                if args.dry_run:
                    continue
                    
                if not success:
                    print(f"❌ Failed to download Tile {i},{j}. Halting.")
                    sys.exit(1)
                    
                # Regrid the tile onto master coordinates
                try:
                    img = Image.open(tile_raw_path)
                    w, h = img.size
                    tile_elev = np.array(img, dtype=np.float32)
                except Exception as e:
                    print(f"❌ Error opening Tile TIFF with Pillow: {e}")
                    sys.exit(1)
                    
                tile_raw_lons = np.linspace(tile_lon_min, tile_lon_max, w)
                tile_raw_lats = np.linspace(tile_lat_max, tile_lat_min, h)
                
                # Sort coordinates
                lon_sort = np.argsort(tile_raw_lons)
                lat_sort = np.argsort(tile_raw_lats)
                
                sorted_tile_lons = tile_raw_lons[lon_sort]
                sorted_tile_lats = tile_raw_lats[lat_sort]
                sorted_tile_elev = tile_elev[np.ix_(lat_sort, lon_sort)]
                
                tile_interpolator = interp.RegularGridInterpolator(
                    (sorted_tile_lats, sorted_tile_lons),
                    sorted_tile_elev,
                    method="linear",
                    bounds_error=False,
                    fill_value=0.0
                )
                
                # Find which master indices fall within this tile bounding box
                # Use slightly larger bounds than tile boundaries to ensure everything gets filled
                buf = 0.001
                lon_indices = np.where((target_lons >= tile_lon_min - buf) & (target_lons <= tile_lon_max + buf))[0]
                lat_indices = np.where((target_lats >= tile_lat_min - buf) & (target_lats <= tile_lat_max + buf))[0]
                
                if len(lon_indices) > 0 and len(lat_indices) > 0:
                    sub_lons = target_lons[lon_indices]
                    sub_lats = target_lats[lat_indices]
                    sub_lon_mesh, sub_lat_mesh = np.meshgrid(sub_lons, sub_lats)
                    points = np.stack([sub_lat_mesh.ravel(), sub_lon_mesh.ravel()], axis=-1)
                    
                    tile_interpolated = tile_interpolator(points).reshape(len(sub_lats), len(sub_lons))
                    
                    # Write to master array
                    for r_idx, lat_idx in enumerate(lat_indices):
                        for c_idx, lon_idx in enumerate(lon_indices):
                            val = tile_interpolated[r_idx, c_idx]
                            master_depth[lat_idx, lon_idx] = val
                            master_mask[lat_idx, lon_idx] = True
                            
                # Cleanup file
                try:
                    tile_raw_path.unlink()
                except OSError:
                    pass
                    
        print(f"\n✅ All {lon_steps * lat_steps} tiles downloaded, regridded, and stitched!")
        
    else:
        # Single tile processing (original logic)
        raw_path = input_dir / "emodnet_bathymetry_raw.tiff"
        
        # Dynamic resolution calculation
        res_val = max(0.00104166, args.resolution / 2.0)
        max_deg = max(width_deg, height_deg)
        if max_deg / res_val > 4000:
            res_val = max_deg / 4000.0
            
        resx_str = f"{res_val:.8f}"
        resy_str = f"{res_val:.8f}"
        
        success = download_emodnet_bathymetry(
            lon_min=args.lon_min,
            lon_max=args.lon_max,
            lat_min=args.lat_min,
            lat_max=args.lat_max,
            output_path=raw_path,
            dry_run=args.dry_run,
            resx=resx_str,
            resy=resy_str,
        )
        
        if not success and not args.dry_run:
            print("❌ Bathymetry preparation halted due to download failure.")
            sys.exit(1)
            
        if not args.dry_run:
            try:
                img = Image.open(raw_path)
                w, h = img.size
                raw_elev = np.array(img, dtype=np.float32)
            except Exception as e:
                print(f"❌ Error opening raw TIFF with Pillow: {e}")
                sys.exit(1)
                
            raw_lons = np.linspace(args.lon_min, args.lon_max, w)
            raw_lats = np.linspace(args.lat_max, args.lat_min, h)
            
            lon_sort = np.argsort(raw_lons)
            lat_sort = np.argsort(raw_lats)
            
            sorted_lons = raw_lons[lon_sort]
            sorted_lats = raw_lats[lat_sort]
            sorted_elev = raw_elev[np.ix_(lat_sort, lon_sort)]
            
            interpolator = interp.RegularGridInterpolator(
                (sorted_lats, sorted_lons),
                sorted_elev,
                method="linear",
                bounds_error=False,
                fill_value=0.0
            )
            
            points = np.stack([lat_mesh.ravel(), lon_mesh.ravel()], axis=-1)
            master_depth = interpolator(points).reshape(len(target_lats), len(target_lons))
            
            # Cleanup file
            try:
                raw_path.unlink()
            except OSError:
                pass
                
    if args.dry_run:
        print("⚡ [DRY RUN] Finished mock execution successfully.")
        return
        
    # Standardize depth format
    master_depth = np.nan_to_num(master_depth, nan=0.0)
    
    # EMODnet depth convention check: make ocean depths positive, elevation negative/zero
    is_depth_positive = np.nanmean(master_depth) > 0
    if not is_depth_positive:
        master_depth = -master_depth
        
    # Enforce strictly positive water depth (0 for land)
    master_depth = np.maximum(master_depth, 0.0)
    
    # --------------------------------------------------
    # 1. SWAN NetCDF Output
    # --------------------------------------------------
    ds_swan = xr.Dataset(
        data_vars={
            "depth": (["latitude", "longitude"], master_depth.astype(np.float32)),
        },
        coords={
            "longitude": (["longitude"], target_lons.astype(np.float32)),
            "latitude": (["latitude"], target_lats.astype(np.float32)),
        },
        attrs={
            "title": "PredSea SWAN Bathymetry Grid",
            "source": "EMODnet Bathymetry DTM WCS (Tiled & Stitched)",
            "resolution_deg": str(args.resolution),
        }
    )
    ds_swan.to_netcdf(swan_path)
    print(f"✅ Processed SWAN Bathymetry saved to {swan_path}")

    # Upload to GCS
    if args.gcs_bucket and not args.no_upload:
        upload_to_gcs(args.gcs_bucket, swan_path, f"static/bathymetry/{file_prefix}_bathymetry_swan.nc")
        print("🎉 Bathymetry successfully uploaded to GCS.")


if __name__ == "__main__":
    main()
