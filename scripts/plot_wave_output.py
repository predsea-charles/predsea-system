#!/usr/bin/env python3
"""
PredSea WW3 Wave Forecast Map Plotter.

Generates high-resolution wave height ($H_s$) heatmaps with wave propagation quivers
from WW3 forecast NetCDF outputs (`ww3_forecast.nc`).

Correctly handles Nautical Wave Direction Convention:
WAVEWATCH III stores wave direction as the direction FROM WHICH waves travel.
This script converts nautical 'from' direction into wave propagation vectors
(pointing TOWARDS where waves are traveling, e.g., from Gibraltar into the Mediterranean).

Usage:
    .venv311/bin/python scripts/plot_wave_output.py \
        --source scratch/diags/alboran_ww3_forecast.nc \
        --output-dir ./wave_plots \
        --region alboran_1km \
        --time-index 0
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HS_NAMES = ("hs", "significant_wave_height", "HS")
DIR_NAMES = ("dir", "mean_wave_direction", "DIR", "wave_mean_direction")
WND_NAMES = ("wnd", "wind_speed", "WND")
LAT_NAMES = ("latitude", "lat", "LAT", "XLAT")
LON_NAMES = ("longitude", "lon", "LON", "XLONG")

def _first_existing(ds: xr.Dataset, names, required: bool = True):
    for name in names:
        if name in ds:
            return name
    if required:
        raise ValueError(f"Dataset is missing required variable from list: {names}")
    return None

def open_dataset(source: str) -> xr.Dataset:
    if source.startswith("gs://"):
        try:
            import gcsfs
            fs = gcsfs.GCSFileSystem()
            print(f"Streaming open from GCS: {source}")
            return xr.open_dataset(fs.open(source, "rb"))
        except ImportError:
            raise SystemExit("Reading directly from GCS requires 'gcsfs' (pip install gcsfs).")
    print(f"Opening local file: {source}")
    return xr.open_dataset(source)

def plot_wave_map(ds: xr.Dataset, time_idx: int, region_id: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    lat_name = _first_existing(ds, LAT_NAMES)
    lon_name = _first_existing(ds, LON_NAMES)
    hs_name = _first_existing(ds, HS_NAMES)
    dir_name = _first_existing(ds, DIR_NAMES, required=False)

    lat = ds[lat_name].values
    lon = ds[lon_name].values
    hs = ds[hs_name]

    # Select time step
    time_dim = next((d for d in ("time", "Time") if d in hs.dims), None)
    if time_dim:
        time_val = str(ds[time_dim].values[time_idx])[:19]
        hs_slice = hs.isel({time_dim: time_idx}).values
        if dir_name:
            dir_slice = ds[dir_name].isel({time_dim: time_idx}).values
        else:
            dir_slice = None
    else:
        time_val = "00:00:00"
        hs_slice = hs.values
        dir_slice = ds[dir_name].values if dir_name else None

    # Ensure 2D spatial arrays
    if lon.ndim == 1 and lat.ndim == 1:
        lon_2d, lat_2d = np.meshgrid(lon, lat)
    else:
        lon_2d, lat_2d = lon, lat

    fig, ax = plt.subplots(figsize=(10, 7), dpi=200)

    # Plot wave height heatmap with viridis colormap
    pcm = ax.pcolormesh(lon_2d, lat_2d, hs_slice, shading="auto", cmap="viridis", vmin=0)
    cbar = fig.colorbar(pcm, ax=ax, label="Significant Wave Height $H_s$ (meters)", pad=0.02)
    cbar.ax.tick_params(labelsize=10)

    # Overlay directional quivers if direction field is present
    if dir_slice is not None:
        stride = max(1, min(lat_2d.shape[0], lat_2d.shape[1]) // 25)
        # WW3 stores nautical direction FROM WHICH waves come.
        # To show propagation direction (TOWARDS where waves travel), add 180 degrees:
        towards_deg = (dir_slice + 180.0) % 360.0
        rad = np.radians(90.0 - towards_deg)  # Convert compass deg to math angle
        u_dir = np.cos(rad)
        v_dir = np.sin(rad)
        
        # Mask out land / NaN cells
        valid_mask = ~np.isnan(hs_slice) & (hs_slice > 0)
        u_dir[~valid_mask] = np.nan
        v_dir[~valid_mask] = np.nan

        ax.quiver(
            lon_2d[::stride, ::stride],
            lat_2d[::stride, ::stride],
            u_dir[::stride, ::stride],
            v_dir[::stride, ::stride],
            color="white",
            scale=30,
            width=0.003,
            alpha=0.8,
        )

    ax.set_title(f"PredSea WW3 Wave Propagation Map — {region_id.upper()}\nTime: {time_val} UTC (Arrows point TOWARDS wave travel)", fontsize=11, fontweight="bold", pad=12)
    ax.set_xlabel("Longitude (°E)", fontsize=10)
    ax.set_ylabel("Latitude (°N)", fontsize=10)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", alpha=0.3)

    out_file = out_dir / f"{region_id}_wave_map_step_{time_idx:02d}.png"
    fig.tight_layout()
    fig.savefig(out_file, dpi=200)
    plt.close(fig)

    print(f"✅ Generated corrected wave propagation map: {out_file}")
    return out_file

def main():
    parser = argparse.ArgumentParser(description="Plot WW3 Wave Forecast Map")
    parser.add_argument("--source", required=True, help="Local file path or gs:// URI to NetCDF file")
    parser.add_argument("--output-dir", default="./wave_plots", help="Directory to save generated PNG maps")
    parser.add_argument("--region", default="alboran_1km", help="Region identifier")
    parser.add_argument("--time-index", type=int, default=0, help="Time index to plot (default: 0)")
    args = parser.parse_args()

    ds = open_dataset(args.source)
    plot_wave_map(ds, args.time_index, args.region, Path(args.output_dir))
    ds.close()

if __name__ == "__main__":
    main()
