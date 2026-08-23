#!/usr/bin/env python3
"""
PredSea WW3 vs. CMEMS / ECMWF Wave Comparison Plotter.

Renders side-by-side maps comparing PredSea WW3 1km high-resolution wave forecasts
against CMEMS / ECMWF regional wave datasets.

Usage:
    .venv311/bin/python scripts/compare_ww3_vs_cmems.py \
        --ww3 scratch/diags/alboran_ww3_forecast.nc \
        --cmems scratch/diags/cmems_alboran_wave.nc \
        --output-dir ./wave_plots \
        --region alboran_1km
"""

import argparse
from pathlib import Path

import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def plot_side_by_side_comparison(ww3_path: Path, cmems_path: Path, out_dir: Path, region_id: str):
    out_dir.mkdir(parents=True, exist_ok=True)

    ds_ww3 = xr.open_dataset(ww3_path)
    ds_cmems = xr.open_dataset(cmems_path)

    # WW3 fields
    ww3_lat = ds_ww3["latitude"].values
    ww3_lon = ds_ww3["longitude"].values
    ww3_hs = ds_ww3["hs"].isel(time=0).values
    ww3_dir = ds_ww3["dir"].isel(time=0).values if "dir" in ds_ww3 else None

    # CMEMS / ECMWF fields
    cmems_lat = ds_cmems["latitude"].values
    cmems_lon = ds_cmems["longitude"].values
    cmems_hs = ds_cmems["VHM0"].isel(time=0).values
    cmems_dir = ds_cmems["VMDR"].isel(time=0).values if "VMDR" in ds_cmems else None

    # 2D Meshgrids
    ww3_lon2d, ww3_lat2d = np.meshgrid(ww3_lon, ww3_lat) if ww3_lon.ndim == 1 else (ww3_lon, ww3_lat)
    cmems_lon2d, cmems_lat2d = np.meshgrid(cmems_lon, cmems_lat) if cmems_lon.ndim == 1 else (cmems_lon, cmems_lat)

    # Shared colorbar limits for fair comparison
    max_hs = max(np.nanmax(ww3_hs), np.nanmax(cmems_hs)) * 1.1

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6), dpi=200, sharex=True, sharey=True)

    # --- SUBPLOT 1: PredSea WW3 1km Forecast ---
    pcm1 = ax1.pcolormesh(ww3_lon2d, ww3_lat2d, ww3_hs, shading="auto", cmap="viridis", vmin=0, vmax=max_hs)
    ax1.set_title(f"PredSea WW3 1km High-Res Forecast\nMax $H_s$: {np.nanmax(ww3_hs):.2f} m", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Longitude (°E)", fontsize=10)
    ax1.set_ylabel("Latitude (°N)", fontsize=10)
    ax1.grid(True, linestyle="--", alpha=0.3)
    ax1.set_aspect("equal", adjustable="box")

    if ww3_dir is not None:
        stride1 = max(1, min(ww3_lat2d.shape) // 20)
        towards1 = (ww3_dir + 180.0) % 360.0
        rad1 = np.radians(90.0 - towards1)
        u1 = np.cos(rad1)
        v1 = np.sin(rad1)
        valid1 = ~np.isnan(ww3_hs) & (ww3_hs > 0)
        u1[~valid1] = np.nan
        v1[~valid1] = np.nan
        ax1.quiver(ww3_lon2d[::stride1, ::stride1], ww3_lat2d[::stride1, ::stride1], u1[::stride1, ::stride1], v1[::stride1, ::stride1], color="white", scale=25, alpha=0.85)

    # --- SUBPLOT 2: CMEMS / ECMWF Reference ---
    pcm2 = ax2.pcolormesh(cmems_lon2d, cmems_lat2d, cmems_hs, shading="auto", cmap="viridis", vmin=0, vmax=max_hs)
    ax2.set_title(f"CMEMS / ECMWF Wave Reference\nMax $H_s$: {np.nanmax(cmems_hs):.2f} m", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Longitude (°E)", fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.3)
    ax2.set_aspect("equal", adjustable="box")

    if cmems_dir is not None:
        stride2 = max(1, min(cmems_lat2d.shape) // 18)
        towards2 = (cmems_dir + 180.0) % 360.0
        rad2 = np.radians(90.0 - towards2)
        u2 = np.cos(rad2)
        v2 = np.sin(rad2)
        valid2 = ~np.isnan(cmems_hs) & (cmems_hs > 0)
        u2[~valid2] = np.nan
        v2[~valid2] = np.nan
        ax2.quiver(cmems_lon2d[::stride2, ::stride2], cmems_lat2d[::stride2, ::stride2], u2[::stride2, ::stride2], v2[::stride2, ::stride2], color="white", scale=25, alpha=0.85)

    # Shared colorbar
    fig.subplots_adjust(right=0.88)
    cbar_ax = fig.add_axes([0.90, 0.15, 0.02, 0.7])
    fig.colorbar(pcm1, cax=cbar_ax, label="Significant Wave Height $H_s$ (meters)")

    fig.suptitle(f"Wave Forecast Comparison — {region_id.upper()} Domain", fontsize=14, fontweight="bold", y=0.98)

    out_file = out_dir / f"{region_id}_ww3_vs_cmems_comparison.png"
    fig.savefig(out_file, dpi=200, bbox_inches="tight")
    plt.close(fig)

    ds_ww3.close()
    ds_cmems.close()

    print(f"✅ Generated side-by-side wave comparison plot: {out_file}")
    return out_file

def main():
    parser = argparse.ArgumentParser(description="Side-by-side WW3 vs CMEMS wave comparison")
    parser.add_argument("--ww3", required=True, help="Path to WW3 NetCDF file")
    parser.add_argument("--cmems", required=True, help="Path to CMEMS NetCDF file")
    parser.add_argument("--output-dir", default="./wave_plots", help="Output directory")
    parser.add_argument("--region", default="alboran_1km", help="Region identifier")
    args = parser.parse_args()

    plot_side_by_side_comparison(Path(args.ww3), Path(args.cmems), Path(args.output_dir), args.region)

if __name__ == "__main__":
    main()
