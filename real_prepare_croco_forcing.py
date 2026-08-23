#!/usr/bin/env python3
"""
Prepare CROCO Initial (ini) and Climatology/Boundary (clm) conditions
from raw 3D Copernicus Marine (CMEMS) datasets.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import datetime as dt
import json
import multiprocessing
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare CROCO initial and boundary/climatology files from CMEMS forcing."
    )
    parser.add_argument(
        "--grid",
        type=Path,
        default=Path("tmp/croco_grid_balearic_1km.nc"),
        help="Path to CROCO grid NetCDF file",
    )
    parser.add_argument(
        "--forcing-dir",
        type=Path,
        default=Path("tmp/forcing-croco-24h"),
        help="Path to raw CMEMS downloaded files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tmp/forcing-croco-24h"),
        help="Path to save croco_ini.nc and croco_clm.nc",
    )
    parser.add_argument(
        "--vertical-levels",
        type=int,
        default=32,
        help="Number of vertical sigma levels",
    )
    parser.add_argument("--theta-s", type=float, default=6.0)
    parser.add_argument("--theta-b", type=float, default=0.0)
    parser.add_argument("--hc-m", type=float, default=10.0)
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Bounded interpolation process count; keep low to avoid multiplying 3-D working arrays",
    )
    return parser.parse_args()


def fill_nans(data: np.ndarray) -> np.ndarray:
    """Propagate nearest non-nan values to avoid boundary interpolation issues."""
    if not np.isnan(data).any():
        return data
    filled = data.copy()
    nans = np.isnan(filled)
    if not nans.all():
        # Clean up 2D or 3D datasets along the lat-lon axes
        for i in range(filled.shape[0]):
            sub = filled[i]
            sub_nans = np.isnan(sub)
            if sub_nans.any() and not sub_nans.all():
                # Fill row-by-row
                mask = ~sub_nans
                for r in range(sub.shape[0]):
                    if sub_nans[r].any():
                        if mask[r].any():
                            sub[r, sub_nans[r]] = np.interp(
                                np.flatnonzero(sub_nans[r]),
                                np.flatnonzero(mask[r]),
                                sub[r, mask[r]]
                            )
    # Fill any remaining NaNs with the overall mean
    if np.isnan(filled).any():
        mean_val = np.nanmean(filled)
        if np.isnan(mean_val):
            mean_val = 0.0
        filled[np.isnan(filled)] = mean_val
    return filled


def interpolate_2d_timestep(t: int, var_data_t: np.ndarray, src_lat: np.ndarray, src_lon: np.ndarray, target_lat: np.ndarray, target_lon: np.ndarray) -> tuple[int, np.ndarray]:
    ssh_raw = fill_nans(var_data_t)
    interpolator = RegularGridInterpolator((src_lat, src_lon), ssh_raw, bounds_error=False, fill_value=None)
    return t, interpolator((target_lat, target_lon))


def croco_s_coordinates(
    levels: int, theta_s: float, theta_b: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Reproduce CROCO 2.1.3 ``NEW_S_COORD`` from ``set_scoord.F``."""
    if levels <= 0:
        raise ValueError("CROCO vertical level count must be positive")
    if theta_s < 0.0 or theta_b < 0.0:
        raise ValueError("CROCO stretching parameters must be non-negative")

    ds = 1.0 / levels
    s_rho = ds * (np.arange(1, levels + 1, dtype=float) - levels - 0.5)
    s_w = ds * (np.arange(0, levels + 1, dtype=float) - levels)

    def csf(s: np.ndarray) -> np.ndarray:
        if theta_s > 0.0:
            csrf = (1.0 - np.cosh(theta_s * s)) / (np.cosh(theta_s) - 1.0)
        else:
            csrf = -(s**2)
        if theta_b > 0.0:
            return (np.exp(theta_b * csrf) - 1.0) / (1.0 - np.exp(-theta_b))
        return csrf

    cs_r = csf(s_rho)
    cs_w = csf(s_w)
    cs_w[0], cs_w[-1] = -1.0, 0.0
    return s_rho, s_w, cs_r, cs_w


def croco_depths(
    h: np.ndarray,
    zeta: np.ndarray,
    s: np.ndarray,
    cs: np.ndarray,
    hc_m: float,
) -> np.ndarray:
    """Return CROCO ``NEW_S_COORD`` depths for rho or w levels."""
    h = np.asarray(h, dtype=float)
    zeta = np.asarray(zeta, dtype=float)
    if h.shape != zeta.shape:
        raise ValueError("bathymetry and sea level must share a horizontal grid")
    if np.any(h <= 0.0):
        raise ValueError("CROCO bathymetry must be positive")
    # CROCO 2.1.3 ``set_depth.F`` uses ``hinv=1/(abs(h)+hc)`` under
    # NEW_S_COORD, then multiplies the static term by ``h*hinv``.  Omitting
    # this normalization can put interior levels below the seabed in shallow
    # cells and makes the generated transport inconsistent with the runtime.
    h_abs = np.abs(h)
    hinv = 1.0 / (h_abs + hc_m)
    z0 = hc_m * s[:, None, None] + cs[:, None, None] * h_abs[None, :, :]
    depths = (
        z0 * h[None, :, :] * hinv[None, :, :]
        + zeta[None, :, :] * (1.0 + z0 * hinv[None, :, :])
    )
    # ``set_depth.F`` initializes the bottom W point directly to ``-h`` and
    # only applies the transform for k=1..N.  Preserve that special endpoint.
    bottom = np.isclose(s, -1.0)
    if np.any(bottom):
        depths[bottom] = -h
    return depths


def depth_average_velocity(velocity: np.ndarray, z_w: np.ndarray) -> np.ndarray:
    """Compute barotropic velocity from thickness-weighted 3-D transport."""
    velocity = np.asarray(velocity, dtype=float)
    layer_thickness = np.diff(np.asarray(z_w, dtype=float), axis=0)
    if velocity.shape != layer_thickness.shape:
        raise ValueError("velocity and CROCO layer-thickness shapes do not agree")
    if np.any(layer_thickness <= 0.0):
        raise ValueError("CROCO layer thickness must be positive")
    return np.sum(velocity * layer_thickness, axis=0) / np.sum(
        layer_thickness, axis=0
    )


def verify_transport_consistency(
    u_3d: np.ndarray,
    v_3d: np.ndarray,
    ubar: np.ndarray,
    vbar: np.ndarray,
    z_w_u: np.ndarray,
    z_w_v: np.ndarray,
    tolerance: float = 1e-4,
) -> None:
    """Fail-closed check comparing ubar/vbar against the vertical integral of u/v."""
    ubar_reconstructed = depth_average_velocity(u_3d, z_w_u)
    vbar_reconstructed = depth_average_velocity(v_3d, z_w_v)

    max_diff_u = float(np.max(np.abs(ubar - ubar_reconstructed)))
    max_diff_v = float(np.max(np.abs(vbar - vbar_reconstructed)))

    if max_diff_u > tolerance or max_diff_v > tolerance:
        raise ValueError(
            f"Barotropic transport mismatch exceeds tolerance {tolerance} m/s: "
            f"max_diff_u={max_diff_u:.6e}, max_diff_v={max_diff_v:.6e}"
        )



def interpolate_3d_timestep(t: int, var_data_t: np.ndarray, src_lat: np.ndarray, src_lon: np.ndarray, src_depth: np.ndarray, target_lat: np.ndarray, target_lon: np.ndarray, s_rho: np.ndarray, cs_r: np.ndarray, h: np.ndarray, zeta: np.ndarray, hc_m: float, N: int) -> tuple[int, np.ndarray]:
    nz_src = len(src_depth)
    ny_tgt, nx_tgt = target_lon.shape
    src_z = -src_depth[::-1]

    # Grid indexing coordinates
    grid_y, grid_x = np.meshgrid(np.arange(ny_tgt), np.arange(nx_tgt), indexing='ij')
    y_idx = np.broadcast_to(grid_y, (N, ny_tgt, nx_tgt))
    x_idx = np.broadcast_to(grid_x, (N, ny_tgt, nx_tgt))

    # 1. Horizontal interpolation for each source depth level
    horiz_staged = np.zeros((nz_src, ny_tgt, nx_tgt), dtype=np.float32)
    var_data_filled = fill_nans(var_data_t)
    for z in range(nz_src):
        interpolator = RegularGridInterpolator((src_lat, src_lon), var_data_filled[z], bounds_error=False, fill_value=None)
        horiz_staged[z] = interpolator((target_lat, target_lon))

    # 2. Vertical interpolation
    local_h = h[:ny_tgt, :nx_tgt]
    local_zeta = zeta[:ny_tgt, :nx_tgt]
    target_z = croco_depths(local_h, local_zeta, s_rho, cs_r, hc_m)
    target_z_clipped = np.clip(target_z, src_z[0], src_z[-1])

    idx = np.searchsorted(src_z, target_z_clipped.ravel())
    idx = np.clip(idx, 1, nz_src - 1)
    idx = idx.reshape(N, ny_tgt, nx_tgt)

    idx_low = idx - 1
    idx_high = idx
    z_low = src_z[idx_low]
    z_high = src_z[idx_high]

    dz = z_high - z_low
    dz = np.where(dz == 0.0, 1.0, dz)
    weight_high = (target_z_clipped - z_low) / dz
    weight_low = 1.0 - weight_high

    src_data_sorted = horiz_staged[::-1]
    val_low = src_data_sorted[idx_low, y_idx, x_idx]
    val_high = src_data_sorted[idx_high, y_idx, x_idx]

    return t, weight_low * val_low + weight_high * val_high


def croco_climatology_times(src_time: np.ndarray) -> dict[str, tuple[str, np.ndarray]]:
    """Return the explicit time axes required by CROCO climatology readers.

    This regional binary is compiled without ``USE_CALENDAR``. CROCO therefore
    expects elapsed model days, not CF-decoded datetimes, and it looks up four
    fixed variable names in the climatology file.
    """
    timestamps = np.asarray(src_time).astype("datetime64[ns]")
    if timestamps.ndim != 1 or timestamps.size < 2:
        raise ValueError("CROCO climatology requires at least two forcing timestamps")
    elapsed_days = (
        (timestamps - timestamps[0]) / np.timedelta64(1, "D")
    ).astype(np.float64)
    if not np.all(np.isfinite(elapsed_days)) or not np.all(np.diff(elapsed_days) > 0):
        raise ValueError("CROCO climatology timestamps must be finite and increasing")
    return {
        name: (name, elapsed_days.copy())
        for name in ("ssh_time", "uclm_time", "tclm_time", "sclm_time")
    }


def main() -> int:
    args = parse_args()
    print("=========================================================================")
    print("🌊 Starting CROCO Forcing Compiler")
    print(f"📂 Grid file: {args.grid}")
    print(f"📂 Forcing directory: {args.forcing_dir}")
    print(f"📂 Output directory: {args.output_dir}")
    print(f"📐 Vertical levels (N): {args.vertical_levels}")
    print("=========================================================================")

    # 1. Load the curvilinear grid
    if not args.grid.exists():
        print(f"❌ Error: Grid file not found: {args.grid}")
        return 1

    grid = xr.open_dataset(args.grid)
    lon_rho = grid["lon_rho"].values
    lat_rho = grid["lat_rho"].values
    lon_u = grid["lon_u"].values
    lat_u = grid["lat_u"].values
    lon_v = grid["lon_v"].values
    lat_v = grid["lat_v"].values
    h = grid["h"].values
    mask_rho = grid["mask_rho"].values

    eta_rho, xi_rho = lon_rho.shape
    eta_u, xi_u = lon_u.shape
    eta_v, xi_v = lon_v.shape
    N = args.vertical_levels

    # Reproduce the exact vertical coordinate compiled into the regional CROCO
    # binary.  A linear ``s*h`` approximation creates a different water column
    # and can excite the split-explicit barotropic mode.
    s_rho, s_w, cs_r, cs_w = croco_s_coordinates(
        N, args.theta_s, args.theta_b
    )
    h_u = 0.5 * (h[:, :-1] + h[:, 1:])
    h_v = 0.5 * (h[:-1, :] + h[1:, :])

    # 2. Check input files
    forcing_files = {
        "currents": args.forcing_dir / "cmems_croco_currents_3d.nc",
        "temp": args.forcing_dir / "cmems_croco_temperature_3d.nc",
        "salinity": args.forcing_dir / "cmems_croco_salinity_3d.nc",
        "sea_level": args.forcing_dir / "cmems_croco_sea_level.nc",
    }

    for name, path in forcing_files.items():
        if not path.exists():
            print(f"❌ Error: Missing raw CMEMS file for {name}: {path}")
            return 1

    # 3. Load forcing datasets
    ds_cur = xr.open_dataset(forcing_files["currents"])
    ds_tem = xr.open_dataset(forcing_files["temp"])
    ds_sal = xr.open_dataset(forcing_files["salinity"])
    ds_ssh = xr.open_dataset(forcing_files["sea_level"])

    # Extract axes from CMEMS
    src_lon = ds_ssh["longitude"].values
    src_lat = ds_ssh["latitude"].values
    src_time = ds_ssh["time"].values
    src_depth = ds_cur["depth"].values

    nt = len(src_time)
    print(f"👉 Loaded {nt} hourly forcing timesteps.")
    print(f"👉 CMEMS bounds: Lon [{src_lon.min():.3f}, {src_lon.max():.3f}], Lat [{src_lat.min():.3f}, {src_lat.max():.3f}]")
    print(f"👉 CMEMS depth layers: {len(src_depth)} layers down to {src_depth.max():.1f}m")

    # Each worker materializes several full 30-level target-grid arrays.  A
    # CPU-sized pool can multiply memory until the kernel kills the process,
    # especially after temperature and salinity outputs are resident.  Keep
    # this independently bounded from CROCO's later MPI rank count.
    if args.workers <= 0:
        raise ValueError("CROCO forcing worker count must be positive")
    max_workers = min(args.workers, multiprocessing.cpu_count())
    print(f"🚀 Initializing parallel forcing compiler with {max_workers} processes...")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Keep multi-gigabyte interpolation arrays outside the run artifact tree.
    # A failed Batch task uploads that tree for diagnosis, so putting scratch
    # files there would create a second failure while collecting diagnostics.
    scratch_dir = Path(tempfile.mkdtemp(prefix="predsea-croco-forcing-"))

    # Interpolate SSH (zeta)
    print("🔄 Interpolating sea level (zeta) in parallel...")
    zeta_clm = np.zeros((nt, eta_rho, xi_rho), dtype=np.float32)
    zos_values = ds_ssh["zos"].values

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                interpolate_2d_timestep,
                t,
                zos_values[t],
                src_lat,
                src_lon,
                lat_rho,
                lon_rho
            )
            for t in range(nt)
        ]
        for fut in futures:
            t, result = fut.result()
            zeta_clm[t] = result

    # 3D interpolation helper (parallelized with ProcessPoolExecutor)
    def interpolate_3d(ds: xr.Dataset, var_name: str, target_lon: np.ndarray, target_lat: np.ndarray, target_h: np.ndarray, target_zeta: np.ndarray, shape_3d: tuple[int, int, int]) -> np.ndarray:
        scratch_path = scratch_dir / f"{var_name}.interpolated.float32"
        out = np.memmap(scratch_path, mode="w+", dtype=np.float32, shape=shape_3d)
        var_values = ds[var_name].values

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    interpolate_3d_timestep,
                    t,
                    var_values[t],
                    src_lat,
                    src_lon,
                    src_depth,
                    target_lat,
                    target_lon,
                    s_rho,
                    cs_r,
                    target_h,
                    target_zeta[t],
                    args.hc_m,
                    N
                )
                for t in range(nt)
            ]
            for fut in futures:
                t, result = fut.result()
                out[t] = result
        out.flush()
        return out

    print("🔄 Interpolating 3D Temperature...")
    temp_clm = interpolate_3d(ds_tem, "thetao", lon_rho, lat_rho, h, zeta_clm, (nt, N, eta_rho, xi_rho))

    print("🔄 Interpolating 3D Salinity...")
    salt_clm = interpolate_3d(ds_sal, "so", lon_rho, lat_rho, h, zeta_clm, (nt, N, eta_rho, xi_rho))

    print("🔄 Interpolating 3D Eastward velocity (u)...")
    zeta_u = 0.5 * (zeta_clm[:, :, :-1] + zeta_clm[:, :, 1:])
    u_clm = interpolate_3d(ds_cur, "uo", lon_u, lat_u, h_u, zeta_u, (nt, N, eta_rho, xi_u))

    print("🔄 Interpolating 3D Northward velocity (v)...")
    zeta_v = 0.5 * (zeta_clm[:, :-1, :] + zeta_clm[:, 1:, :])
    v_clm = interpolate_3d(ds_cur, "vo", lon_v, lat_v, h_v, zeta_v, (nt, N, eta_v, xi_v))

    print("🔄 Computing vertically integrated velocities (ubar, vbar)...")
    ubar_clm = np.empty((nt, eta_u, xi_u), dtype=np.float32)
    vbar_clm = np.empty((nt, eta_v, xi_v), dtype=np.float32)
    for t in range(nt):
        z_w_u = croco_depths(h_u, zeta_u[t], s_w, cs_w, args.hc_m)
        z_w_v = croco_depths(h_v, zeta_v[t], s_w, cs_w, args.hc_m)
        ubar_clm[t] = depth_average_velocity(u_clm[t], z_w_u)
        vbar_clm[t] = depth_average_velocity(v_clm[t], z_w_v)
        verify_transport_consistency(
            u_clm[t], v_clm[t], ubar_clm[t], vbar_clm[t], z_w_u, z_w_v, tolerance=1e-4
        )
    print("✅ Verified barotropic transport consistency (tolerance=1e-4 m/s)")

    # Pad forcing arrays by 1 timestep (edge padding) so linear interpolation at t = forecast_hours
    # has a valid upper time record and doesn't trigger GET_TCLIMA out-of-bounds error.
    if len(src_time) > 1:
        time_step = src_time[1] - src_time[0]
    else:
        time_step = np.timedelta64(1, "h")
    src_time_padded = np.append(src_time, src_time[-1] + time_step)

    zeta_clm_pad = np.pad(zeta_clm, ((0, 1), (0, 0), (0, 0)), mode="edge")
    temp_clm_pad = np.pad(temp_clm, ((0, 1), (0, 0), (0, 0), (0, 0)), mode="edge")
    salt_clm_pad = np.pad(salt_clm, ((0, 1), (0, 0), (0, 0), (0, 0)), mode="edge")
    u_clm_pad = np.pad(u_clm, ((0, 1), (0, 0), (0, 0), (0, 0)), mode="edge")
    v_clm_pad = np.pad(v_clm, ((0, 1), (0, 0), (0, 0), (0, 0)), mode="edge")
    ubar_clm_pad = np.pad(ubar_clm, ((0, 1), (0, 0), (0, 0)), mode="edge")
    vbar_clm_pad = np.pad(vbar_clm, ((0, 1), (0, 0), (0, 0)), mode="edge")

    # Save output datasets
    clm_path = args.output_dir / "croco_clm.nc"
    bry_path = args.output_dir / "croco_bry.nc"
    ini_path = args.output_dir / "croco_ini.nc"

    # Save Climatology dataset (all timesteps)
    print(f"💾 Saving Climatology/Boundary forcing to: {clm_path}...")
    clm_times = croco_climatology_times(src_time_padded)
    ds_clm = xr.Dataset(
        data_vars={
            # This CROCO build resolves sea-surface-height climatology by its
            # canonical forcing name (SSH), not the ROMS history name (zeta).
            "SSH": (("ssh_time", "eta_rho", "xi_rho"), zeta_clm_pad),
            "temp": (("tclm_time", "s_rho", "eta_rho", "xi_rho"), temp_clm_pad),
            "salt": (("sclm_time", "s_rho", "eta_rho", "xi_rho"), salt_clm_pad),
            "u": (("uclm_time", "s_rho", "eta_u", "xi_u"), u_clm_pad),
            "v": (("uclm_time", "s_rho", "eta_v", "xi_v"), v_clm_pad),
            "ubar": (("uclm_time", "eta_u", "xi_u"), ubar_clm_pad),
            "vbar": (("uclm_time", "eta_v", "xi_v"), vbar_clm_pad),
        },
        coords={
            **clm_times,
            "s_rho": s_rho,
            "lon_rho": (("eta_rho", "xi_rho"), lon_rho),
            "lat_rho": (("eta_rho", "xi_rho"), lat_rho),
        }
    )
    for time_name in clm_times:
        ds_clm[time_name].attrs.update(
            long_name="elapsed time since forecast initialization",
            units="days",
        )
    encoding_clm = {var: {"zlib": True, "complevel": 1} for var in ds_clm.data_vars}
    ds_clm.to_netcdf(clm_path, encoding=encoding_clm)

    # Explicit side variables are required by CROCO's FRC_BRY readers; the
    # full-domain climatology file does not constrain an open boundary.
    bry_vars = {}
    sides = {
        "west": (0, slice(None), "eta_rho", "eta_u", "eta_v"),
        "east": (-1, slice(None), "eta_rho", "eta_u", "eta_v"),
        "south": (slice(None), 0, "xi_rho", "xi_u", "xi_v"),
        "north": (slice(None), -1, "xi_rho", "xi_u", "xi_v"),
    }
    for side, (ii, jj, rho_axis, u_axis, v_axis) in sides.items():
        bry_vars[f"zeta_{side}"] = (("bry_time", rho_axis), zeta_clm_pad[:, jj, ii])
        bry_vars[f"temp_{side}"] = (("bry_time", "s_rho", rho_axis), temp_clm_pad[:, :, jj, ii])
        bry_vars[f"salt_{side}"] = (("bry_time", "s_rho", rho_axis), salt_clm_pad[:, :, jj, ii])
        bry_vars[f"u_{side}"] = (("bry_time", "s_rho", u_axis), u_clm_pad[:, :, jj, ii])
        bry_vars[f"v_{side}"] = (("bry_time", "s_rho", v_axis), v_clm_pad[:, :, jj, ii])
        bry_vars[f"ubar_{side}"] = (("bry_time", u_axis), ubar_clm_pad[:, jj, ii])
        bry_vars[f"vbar_{side}"] = (("bry_time", v_axis), vbar_clm_pad[:, jj, ii])
    bry_time = clm_times["ssh_time"][1]
    ds_bry = xr.Dataset(bry_vars, coords={"bry_time": bry_time, "s_rho": s_rho})
    ds_bry["bry_time"].attrs.update(long_name="boundary time", units="days")
    if not all(bool(np.isfinite(ds_bry[name]).all()) for name in ds_bry.data_vars):
        raise ValueError("CROCO boundary forcing contains non-finite values")
    ds_bry.to_netcdf(
        bry_path,
        encoding={var: {"zlib": True, "complevel": 1} for var in ds_bry.data_vars},
    )

    # Save Initial condition dataset (t=0)
    print(f"💾 Saving Initial conditions to: {ini_path}...")
    ds_ini = xr.Dataset(
        data_vars={
            "zeta": (("ocean_time", "eta_rho", "xi_rho"), zeta_clm[0:1]),
            "temp": (("ocean_time", "s_rho", "eta_rho", "xi_rho"), temp_clm[0:1]),
            "salt": (("ocean_time", "s_rho", "eta_rho", "xi_rho"), salt_clm[0:1]),
            "u": (("ocean_time", "s_rho", "eta_u", "xi_u"), u_clm[0:1]),
            "v": (("ocean_time", "s_rho", "eta_v", "xi_v"), v_clm[0:1]),
            "ubar": (("ocean_time", "eta_u", "xi_u"), ubar_clm[0:1]),
            "vbar": (("ocean_time", "eta_v", "xi_v"), vbar_clm[0:1]),
            "scrum_time": (("ocean_time",), src_time[0:1]),
        },
        coords={
            "ocean_time": src_time[0:1],
            "s_rho": s_rho,
            "lon_rho": (("eta_rho", "xi_rho"), lon_rho),
            "lat_rho": (("eta_rho", "xi_rho"), lat_rho),
        }
    )
    encoding_ini = {var: {"zlib": True, "complevel": 1} for var in ds_ini.data_vars}
    ds_ini.to_netcdf(ini_path, encoding=encoding_ini)

    # The NetCDF outputs are now self-contained. Close every view of the
    # disk-backed arrays before removing their temporary backing files.
    ds_clm.close()
    ds_bry.close()
    ds_ini.close()
    for array in (temp_clm, salt_clm, u_clm, v_clm):
        array.flush()
    del ds_clm, ds_bry, ds_ini, temp_clm, salt_clm, u_clm, v_clm
    shutil.rmtree(scratch_dir)

    print("=========================================================================")
    print("✅ CROCO Forcing compiled successfully!")
    print(f"   - Climatology: {clm_path} ({clm_path.stat().st_size / (1024*1024):.1f} MB)")
    print(f"   - Boundary: {bry_path} ({bry_path.stat().st_size / (1024*1024):.1f} MB)")
    print(f"   - Initial State: {ini_path} ({ini_path.stat().st_size / (1024*1024):.1f} MB)")
    print("=========================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
