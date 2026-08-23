#!/usr/bin/env python3
"""
PredSea WW3 Grid Preparation Utility (Phase 0 of the WW3 migration --
docs/ww3-migration-plan-2026-08-04.md).

Generates the two inputs `ww3_grid` needs for a rectilinear (RECT) grid:
  1. `ww3_grid.nml` -- the grid/spectrum/timestep/boundary namelist.
  2. A free-format ASCII depth file in WW3's expected convention.

Schema verified directly against the live NOAA-EMC/WW3 `develop` branch
source (`model/nml/ww3_grid.nml`, fetched 2026-08-04) -- namelist field
names, the CFL timestep formula, and the depth-sign convention below are
not guesses, they're transcribed from that file's own documentation
comments. What IS an assumption (flagged inline below) is which specific
values to pick for this project's regions/switch config -- reasonable
defaults chosen to match the existing SWAN setup where a direct analog
exists (NK=32, NTH=36 matching prepare_swan_run.py's frequencies/directions),
and standard WW3 example-config defaults elsewhere (XFR, FREQ1).

Depth sign convention (load-bearing, verified from source comments):
WW3 wants depth NEGATIVE below mean sea level -- the opposite of this
project's existing SWAN bathymetry files, which store depth POSITIVE for
water (see scripts/prepare_bathymetry.py). This script negates the
existing, already-GSHHG-validated SWAN bathymetry NetCDFs rather than
re-deriving bathymetry from EMODnet again -- reuses verified-correct data.

Usage:
    python3 scripts/prepare_ww3_grid.py --region tyrrhenian_1km \\
        --swan-bathymetry assets/static_grids/tyrrhenian_1km_bathymetry_swan.nc \\
        --output-dir simulation/marine/ww3/grids/tyrrhenian_1km
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import xarray as xr

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGIONS_DIR = PROJECT_ROOT / "simulation" / "marine" / "regions"

# Standard WW3 example-config defaults (verified in model/nml/ww3_grid.nml's
# own template) -- reasonable starting point, not project-specific tuning.
DEFAULT_XFR = 1.1
DEFAULT_FREQ1_HZ = 0.04118
# Matches prepare_swan_run.py's SWAN directions/frequencies counts, so the
# two models are being asked to resolve the spectrum at comparable
# resolution -- an apples-to-apples starting point for Phase 1 validation.
DEFAULT_NK = 32
DEFAULT_NTH = 36

# Metres per degree approximation already used elsewhere in this codebase
# (scripts/prepare_bathymetry.py's load_region_bbox, submit_gcp_batch_simulation.py).
METERS_PER_DEGREE = 111_000.0

GRAVITY = 9.8  # m/s^2, matches the formula given in ww3_grid.nml's own comments


def load_region(region_id: str) -> dict:
    profile_path = REGIONS_DIR / f"{region_id}.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"No region profile found at {profile_path}")
    return json.loads(profile_path.read_text())


def compute_cfl_timesteps(dxy_m: float, freq1_hz: float, strong_currents: bool) -> dict:
    """Reproduces the exact formula documented in WW3's own ww3_grid.nml
    template comments:

        Tcfl = DXY / (G / (FREQ1*4*Pi))
        DTXY  ~= 90% Tcfl
        DTMAX ~= 3 * DTXY
        DTKTH ~= DTMAX / 2   (light/no currents)
        DTKTH ~= DTMAX / 10  (strong currents)
        DTMIN ~= 10s (standard default, 5-60s range per docs)

    `strong_currents` should be set True for regions where CROCO-forced
    currents are known to be significant (e.g. alboran_1km, given the
    Gibraltar Strait) -- defaults to the light-current assumption
    otherwise. This is an assumption, not verified against this project's
    actual current-speed data; revisit if Phase 1 validation shows
    refraction-related instability.
    """
    tcfl = dxy_m / (GRAVITY / (freq1_hz * 4 * math.pi))
    dtxy = 0.9 * tcfl
    dtmax = 3 * dtxy
    dtkth = dtmax / (10 if strong_currents else 2)
    dtmin = 10.0
    return {
        "DTMAX": round(dtmax, 1),
        "DTXY": round(dtxy, 1),
        "DTKTH": round(dtkth, 1),
        "DTMIN": dtmin,
        "_tcfl_unrounded": tcfl,
    }


def write_depth_file(swan_bathymetry_path: Path, output_path: Path) -> tuple[int, int, np.ndarray]:
    """Convert an existing, GSHHG-validated SWAN bathymetry NetCDF (depth
    POSITIVE for water) into WW3's free-format ASCII depth convention
    (depth NEGATIVE below mean sea level), written bottom-to-top per row
    (IDLA=1, WW3's default layout).

    Returns (nx, ny, depth_ww3) -- nx/ny so the caller can populate
    RECT_NML with matching dimensions (this is deliberately the single
    source of truth for grid size, rather than recomputing it separately
    from the bbox and risking an off-by-one mismatch against the actual
    depth file's shape), and depth_ww3 (already in bottom-to-top order) so
    the caller can build a coastline-aware boundary point list from the
    same array that was actually written to disk, instead of re-deriving
    land/sea from the original SWAN file a second time.
    """
    ds = xr.open_dataset(swan_bathymetry_path)
    depth_swan = np.asarray(ds["depth"].values, dtype=np.float64)  # positive = water
    lat = np.asarray(ds["latitude"].values)
    ds.close()

    ny, nx = depth_swan.shape
    depth_ww3 = -depth_swan  # negate: water becomes negative, land (was <=0) becomes >=0

    # Ensure bottom-to-top row order (IDLA=1) regardless of the source
    # file's own latitude ordering.
    if lat[0] > lat[-1]:
        depth_ww3 = depth_ww3[::-1, :]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for row in depth_ww3:
            f.write(" ".join(f"{v:.2f}" for v in row))
            f.write("\n")

    return nx, ny, depth_ww3


def build_coastline_aware_boundary_points(
    depth_ww3: np.ndarray, nx: int, ny: int, zlim: float = -0.10
) -> list[tuple[int, int, bool]]:
    """Perimeter boundary points, restricted to genuinely open-water cells.

    UPDATE 2026-08-04, after the first real ww3_grid run on alboran_1km:
    this replaces the original "trace the whole rectangle" approach, which
    assumed every bbox edge is open water. That assumption failed loudly
    -- alboran_1km's north/south bbox edges run along the Spanish/Moroccan
    coast, and WW3 correctly refused to mark those land cells as active
    boundary points (a wall of "CANNOT BE GIVEN THE STATUS 2" warnings,
    one per rejected point). Only 66 of ~1670 perimeter cells survived
    with the old logic -- nowhere near the real east/west open-water edges'
    actual extent.

    This version scans each of the 4 edges for contiguous runs of actual
    sea points (per GRID_NML's own rule: excluded/land if depth > zlim)
    and emits one connected run per contiguous segment, starting a new
    segment (connect=False) whenever a run is broken by a land point or an
    edge boundary -- so a land-heavy edge (alboran's north/south) just
    gets however many real open-water segments it actually has, instead of
    being force-fit as one connected line across land.

    depth_ww3 must be in the same bottom-to-top row order written to the
    depth file (IDLA=1), so index [0] is the southernmost row = WW3's
    iy=1.
    """
    is_land = depth_ww3 > zlim  # matches GRID_NML%ZLIM's own documented rule

    def edge_runs(coords: list[tuple[int, int]]) -> list[tuple[int, int, bool]]:
        points: list[tuple[int, int, bool]] = []
        prev_was_sea = False
        for ix, iy in coords:
            if is_land[iy - 1, ix - 1]:
                prev_was_sea = False
                continue
            points.append((ix, iy, prev_was_sea))
            prev_was_sea = True
        return points

    # Each corner appears exactly once across all 4 lists, to avoid a
    # duplicate boundary point entry at shared corners.
    bottom = [(ix, 1) for ix in range(1, nx + 1)]
    right = [(nx, iy) for iy in range(2, ny + 1)]
    top = [(ix, ny) for ix in range(nx - 1, 0, -1)]
    left = [(1, iy) for iy in range(ny - 1, 1, -1)]

    boundary_points: list[tuple[int, int, bool]] = []
    for edge in (bottom, right, top, left):
        boundary_points.extend(edge_runs(edge))

    return boundary_points


def render_grid_nml(
    region_id: str,
    nx: int,
    ny: int,
    sx_deg: float,
    sy_deg: float,
    x0: float,
    y0: float,
    timesteps: dict,
    boundary_points: list[tuple[int, int, bool]],
    depth_filename: str,
) -> str:
    inbnd_lines = "\n".join(
        f"  INBND_POINT({i+1})         = {ix} {iy}  {'T' if connect else 'F'}"
        for i, (ix, iy, connect) in enumerate(boundary_points)
    )
    return f"""\
! Generated by scripts/prepare_ww3_grid.py for region '{region_id}'.
! Schema verified against NOAA-EMC/WW3 develop branch model/nml/ww3_grid.nml
! (fetched 2026-08-04) -- see that script's module docstring for what is
! verified vs. assumed in this file's specific values.

&SPECTRUM_NML
  SPECTRUM%XFR           =  {DEFAULT_XFR}
  SPECTRUM%FREQ1         =  {DEFAULT_FREQ1_HZ}
  SPECTRUM%NK            =  {DEFAULT_NK}
  SPECTRUM%NTH           =  {DEFAULT_NTH}
/

&RUN_NML
  RUN%FLCX            = T
  RUN%FLCY            = T
  RUN%FLCTH           = T
  RUN%FLSOU           = T
/

&TIMESTEPS_NML
  TIMESTEPS%DTMAX         =  {timesteps['DTMAX']}
  TIMESTEPS%DTXY          =  {timesteps['DTXY']}
  TIMESTEPS%DTKTH         =  {timesteps['DTKTH']}
  TIMESTEPS%DTMIN         =  {timesteps['DTMIN']}
/

&GRID_NML
  GRID%NAME              =  '{region_id.upper()}'
  GRID%NML               =  'namelists.nml'
  GRID%TYPE              =  'RECT'
  GRID%COORD             =  'SPHE'
  GRID%CLOS              =  'NONE'
  GRID%ZLIM              =  -0.10
  GRID%DMIN              =  2.5
/

&RECT_NML
  RECT%NX                =  {nx}
  RECT%NY                =  {ny}
  RECT%SX                =  {sx_deg:.8f}
  RECT%SY                =  {sy_deg:.8f}
  RECT%SF                =  1.
  RECT%X0                =  {x0:.6f}
  RECT%Y0                =  {y0:.6f}
  RECT%SF0               =  1.
/

&DEPTH_NML
  DEPTH%SF             = 1.
  DEPTH%FILENAME       = '{depth_filename}'
  DEPTH%IDLA           = 1
  DEPTH%IDFM           = 1
/

! No separate MASK_NML: land/sea is derived automatically from GRID%ZLIM
! against the depth file above (points shallower than ZLIM are excluded),
! per ww3_grid.nml's own documented behavior -- one fewer file to keep in
! sync with the depth data.

&INBND_COUNT_NML
  INBND_COUNT%N_POINT    = {len(boundary_points)}
/

&INBND_POINT_NML
{inbnd_lines}
/
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True, help="Region ID (e.g., tyrrhenian_1km, balearic_1km)")
    parser.add_argument(
        "--swan-bathymetry",
        type=Path,
        help="Path to the existing, GSHHG-validated SWAN bathymetry NetCDF for this region "
        "(defaults to assets/static_grids/{region}_bathymetry_swan.nc)",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to write ww3_grid.nml + depth file into")
    parser.add_argument(
        "--strong-currents",
        action="store_true",
        help="Use the strong-current DTKTH divisor (/10 instead of /2). Recommended for alboran_1km "
        "given the Gibraltar Strait; leave unset for the Phase 0 target regions.",
    )
    args = parser.parse_args()

    region = load_region(args.region)
    bbox = region["bbox"]
    resolution_deg = region["horizontal_resolution_m"] / METERS_PER_DEGREE

    swan_bathy_path = args.swan_bathymetry or (
        PROJECT_ROOT / "assets" / "static_grids" / f"{args.region}_bathymetry_swan.nc"
    )
    if not swan_bathy_path.exists():
        raise FileNotFoundError(
            f"No existing SWAN bathymetry found at {swan_bathy_path} -- generate it first via "
            f"scripts/prepare_bathymetry.py --region {args.region}, or pass --swan-bathymetry explicitly."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    depth_filename = "depth.inp"
    nx, ny, depth_ww3 = write_depth_file(swan_bathy_path, args.output_dir / depth_filename)
    print(f"Wrote depth file: {args.output_dir / depth_filename} ({nx} x {ny} points)")

    dxy_m = resolution_deg * METERS_PER_DEGREE
    timesteps = compute_cfl_timesteps(dxy_m, DEFAULT_FREQ1_HZ, args.strong_currents)
    print(f"CFL-derived timesteps for dxy={dxy_m:.0f}m: {timesteps}")

    boundary_points = build_coastline_aware_boundary_points(depth_ww3, nx, ny)
    print(f"Boundary points (coastline-aware, sea cells only): {len(boundary_points)}")

    nml_content = render_grid_nml(
        region_id=args.region,
        nx=nx,
        ny=ny,
        sx_deg=resolution_deg,
        sy_deg=resolution_deg,
        x0=bbox["longitude_min"],
        y0=bbox["latitude_min"],
        timesteps=timesteps,
        boundary_points=boundary_points,
        depth_filename=depth_filename,
    )
    nml_path = args.output_dir / "ww3_grid.nml"
    nml_path.write_text(nml_content)
    print(f"Wrote grid namelist: {nml_path}")

    # Minimal companion namelists.nml -- WW3 falls back to documented
    # defaults for any switch-dependent physics namelist (e.g. ST4/STAB2
    # tunables) not explicitly present here. Not yet tuned; revisit during
    # Phase 1 validation against the SWAN baseline if defaults look off.
    namelists_path = args.output_dir / "namelists.nml"
    if not namelists_path.exists():
        namelists_path.write_text(
            "! Intentionally minimal -- relying on WW3's documented defaults\n"
            "! for ST4/STAB2/BT4/PR3/UQ physics tunables (see switch_predsea.md\n"
            "! for the switch choices this pairs with). Revisit during Phase 1\n"
            "! validation if output looks physically off vs. the SWAN baseline.\n"
        )
        print(f"Wrote placeholder namelists.nml: {namelists_path}")

    print(
        "\nNext step: run `ww3_grid` inside the ww3-batch container against these "
        f"two files to produce mod_def.ww3 for '{args.region}' -- this script only "
        "prepares the inputs, it cannot execute the Fortran preprocessor itself."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
