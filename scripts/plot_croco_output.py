#!/usr/bin/env python3
"""
PredSea CROCO Output Plotter.

Quick-look plots for a completed CROCO forecast NetCDF: sea surface temperature,
sea surface salinity, sea level, and surface current speed/direction (quiver over
speed). Reads directly from GCS (streaming, via gcsfs) or from a local file --
matches this repo's "no local dataset downloads" policy (docs/OPERATIONS.md) while
still letting you plug in a local file for offline work.

Usage:
    # Direct from GCS (no download needed):
    .venv/bin/python3 scripts/plot_croco_output.py \\
        --source gs://predsea-daily-outputs-test/predictions/2026-07-29/runs/2026-07-29T2130Z/gulf_of_lion_1km/gulf_of_lion_1km_croco_forecast.nc \\
        --output-dir ./croco_plots --time-index 0

    # From a local file already downloaded with gsutil cp:
    .venv/bin/python3 scripts/plot_croco_output.py --source ./gulf_of_lion_1km_croco_forecast.nc --output-dir ./croco_plots
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Same variable-name conventions already confirmed against real CROCO output in
# scripts/croco_forecast_ingestor.py -- kept identical here so this script agrees
# with what the ingestor considers "the" u/v/temp/salt/zeta field.
ROMS_U_NAMES = ("u", "uo", "u_current", "eastward_sea_water_velocity")
ROMS_V_NAMES = ("v", "vo", "v_current", "northward_sea_water_velocity")
ROMS_TEMP_NAMES = ("temp", "tos", "sst", "temperature_surface", "sea_surface_temperature")
ROMS_SALT_NAMES = ("salt", "sos", "salinity", "sea_surface_salinity")
ROMS_ZETA_NAMES = ("zeta", "zos", "ssh", "sea_surface_height")
LAT_NAMES = ("lat_rho", "latitude", "lat", "XLAT", "nav_lat")
LON_NAMES = ("lon_rho", "longitude", "lon", "XLONG", "nav_lon")


def _first_existing(ds: xr.Dataset, names, required: bool = True):
    for name in names:
        if name in ds:
            return name
    if required:
        raise ValueError(f"Dataset is missing one of required fields: {', '.join(names)}")
    return None


def _surface_slice(da: xr.DataArray, time_idx: int):
    """Reduces a (time[, s_rho], eta_rho, xi_rho) array to a 2D surface field at
    the given time index. CROCO's s_rho convention: index -1 is the surface layer,
    index 0 is the seabed (same convention already used in croco_forecast_ingestor.py)."""
    time_dim = next((d for d in ("time", "Time", "ocean_time", "time_counter") if d in da.dims), None)
    if time_dim:
        da = da.isel({time_dim: time_idx})
    for depth_dim in ("s_rho", "s_w"):
        if depth_dim in da.dims:
            da = da.isel({depth_dim: -1})
    return da


def open_dataset(source: str) -> xr.Dataset:
    if source.startswith("gs://"):
        try:
            import gcsfs
        except ImportError:
            raise SystemExit(
                "Reading directly from GCS needs gcsfs (pip install gcsfs). "
                "Alternatively, `gsutil cp` the file locally first and pass that path as --source."
            )
        fs = gcsfs.GCSFileSystem()
        print(f"streaming open (no download): {source}")
        return xr.open_dataset(fs.open(source, "rb"))
    print(f"opening local file: {source}")
    return xr.open_dataset(source)


def plot_scalar_field(lon, lat, field, title, cbar_label, out_path, cmap="viridis"):
    fig, ax = plt.subplots(figsize=(8, 6))
    mesh = ax.pcolormesh(lon, lat, field, shading="auto", cmap=cmap)
    fig.colorbar(mesh, ax=ax, label=cbar_label)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"wrote {out_path}")


def plot_currents(lon, lat, u, v, title, out_path, quiver_stride=8):
    speed = np.sqrt(u ** 2 + v ** 2)
    fig, ax = plt.subplots(figsize=(8, 6))
    mesh = ax.pcolormesh(lon, lat, speed, shading="auto", cmap="plasma")
    fig.colorbar(mesh, ax=ax, label="current speed (m/s)")
    sl = (slice(None, None, quiver_stride), slice(None, None, quiver_stride))
    ax.quiver(lon[sl], lat[sl], u[sl], v[sl], color="white", scale=20, width=0.002)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"wrote {out_path}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Plot a completed CROCO forecast NetCDF (SST, SSS, sea level, surface currents).")
    parser.add_argument("--source", required=True, help="gs://... path or local path to the *_croco_forecast.nc file.")
    parser.add_argument("--output-dir", default="./croco_plots", help="Directory to write PNG plots into.")
    parser.add_argument("--time-index", type=int, default=0, help="Time step index to plot (0 = first forecast hour).")
    parser.add_argument("--region-label", default=None, help="Label for plot titles (defaults to inferring from --source filename).")
    args = parser.parse_args(argv)

    region_label = args.region_label or Path(args.source).name.replace("_croco_forecast.nc", "")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open_dataset(args.source) as ds:
        lat_name = _first_existing(ds, LAT_NAMES, required=True)
        lon_name = _first_existing(ds, LON_NAMES, required=True)
        lat = ds[lat_name].values
        lon = ds[lon_name].values
        if lat.ndim == 1 and lon.ndim == 1:
            lon, lat = np.meshgrid(lon, lat)

        time_dim = next((d for d in ("time", "Time", "ocean_time", "time_counter") if d in ds.sizes), None)
        n_times = ds.sizes.get(time_dim, 1) if time_dim else 1
        t_idx = args.time_index
        if t_idx >= n_times:
            print(f"--time-index {t_idx} out of range (dataset has {n_times} steps); clamping to {n_times - 1}.")
            t_idx = n_times - 1

        lead_label = f"t+{t_idx}h" if time_dim else "single time step"
        title_suffix = f"{region_label} CROCO ({lead_label})"

        temp_name = _first_existing(ds, ROMS_TEMP_NAMES, required=False)
        if temp_name:
            field = _surface_slice(ds[temp_name], t_idx).values
            if np.nanmax(field) > 100.0:  # Kelvin -> Celsius
                field = field - 273.15
            plot_scalar_field(lon, lat, field, f"Sea Surface Temperature — {title_suffix}", "°C", out_dir / f"{region_label}_sst_t{t_idx}.png", cmap="turbo")

        salt_name = _first_existing(ds, ROMS_SALT_NAMES, required=False)
        if salt_name:
            field = _surface_slice(ds[salt_name], t_idx).values
            plot_scalar_field(lon, lat, field, f"Sea Surface Salinity — {title_suffix}", "psu", out_dir / f"{region_label}_sss_t{t_idx}.png", cmap="viridis")

        zeta_name = _first_existing(ds, ROMS_ZETA_NAMES, required=False)
        if zeta_name:
            field = _surface_slice(ds[zeta_name], t_idx).values
            plot_scalar_field(lon, lat, field, f"Sea Level (zeta) — {title_suffix}", "m", out_dir / f"{region_label}_zeta_t{t_idx}.png", cmap="RdBu_r")

        u_name = _first_existing(ds, ROMS_U_NAMES, required=False)
        v_name = _first_existing(ds, ROMS_V_NAMES, required=False)
        if u_name and v_name:
            u = _surface_slice(ds[u_name], t_idx).values
            v = _surface_slice(ds[v_name], t_idx).values
            # CROCO's raw u/v live on staggered xi_u/xi_v, eta_u/eta_v grids
            # (each one cell smaller than rho in a different dimension) unless this
            # file was already regridded onto rho points by the postprocessing step.
            # For a quick-look plot, trim u, v, and the rho coords down to their
            # common overlapping shape rather than doing a full C-grid
            # interpolation -- good enough to see the current field, not meant to
            # replace scripts/vtk_to_netcdf.py's proper C-grid handling.
            common_rows = min(u.shape[0], v.shape[0], lon.shape[0])
            common_cols = min(u.shape[1], v.shape[1], lon.shape[1])
            u = u[:common_rows, :common_cols]
            v = v[:common_rows, :common_cols]
            lon_uv = lon[:common_rows, :common_cols]
            lat_uv = lat[:common_rows, :common_cols]
            plot_currents(lon_uv, lat_uv, u, v, f"Surface Currents — {title_suffix}", out_dir / f"{region_label}_currents_t{t_idx}.png")

    print(f"\nDone. Plots written to {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
