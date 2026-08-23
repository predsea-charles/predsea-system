#!/usr/bin/env python3
"""diagnose_layer_thickness.py — offline check for degenerate CROCO s-levels.

Usage:
    python diagnose_layer_thickness.py --grid croco_grid.nc --hc-m 10.0 --theta-s 6.0 --theta-b 0.0
"""
import argparse
import numpy as np
import xarray as xr
from prepare_croco_forcing import croco_s_coordinates, croco_depths  # reuse real code

def diagnose(h, mask, s_w, cs_w, hc_m, label):
    zeta = np.zeros_like(h)
    z_w = croco_depths(h, zeta, s_w, cs_w, hc_m)
    thickness = np.diff(z_w, axis=0)
    bad_cols = np.where(np.any(thickness <= 0, axis=0))
    n_bad = bad_cols[0].size
    print(f"\n[{label}] non-positive-thickness columns: {n_bad} / {h.size}")
    for j, i in list(zip(*bad_cols))[:20]:
        print(f"  j={j:4d} i={i:4d}  h={h[j,i]:8.3f}  mask={mask[j,i]}  "
              f"min_thickness={thickness[:,j,i].min():.4f}  "
              f"z_w={np.array2string(z_w[:,j,i], precision=2, max_line_width=200)}")
    return n_bad

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", required=True)
    ap.add_argument("--hc-m", type=float, default=10.0)
    ap.add_argument("--theta-s", type=float, default=6.0)
    ap.add_argument("--theta-b", type=float, default=0.0)
    ap.add_argument("--levels", type=int, default=32)
    args = ap.parse_args()

    grid = xr.open_dataset(args.grid)
    h = grid["h"].values
    mask_rho = grid["mask_rho"].values
    h_u = 0.5 * (h[:, :-1] + h[:, 1:])
    h_v = 0.5 * (h[:-1, :] + h[1:, :])
    mask_u = mask_rho[:, :-1] & mask_rho[:, 1:]
    mask_v = mask_rho[:-1, :] & mask_rho[1:, :]

    _, s_w, _, cs_w = croco_s_coordinates(args.levels, args.theta_s, args.theta_b)

    n_u = diagnose(h_u, mask_u, s_w, cs_w, args.hc_m, "u-points")
    n_v = diagnose(h_v, mask_v, s_w, cs_w, args.hc_m, "v-points")

    print(f"\nSUMMARY: {n_u} bad u-columns, {n_v} bad v-columns "
          f"(hc_m={args.hc_m}, theta_s={args.theta_s}, theta_b={args.theta_b})")
    print("If bad columns cluster where mask==0 or where h is near hc_m, "
          "that confirms the coastline/hc_m degeneracy hypothesis.")

if __name__ == "__main__":
    main()
