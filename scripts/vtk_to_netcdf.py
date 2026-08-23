#!/usr/bin/env python3
"""
Convert parallel VTK XML (PVTS/VTS) output files from SWAN MPI simulations
into a single canonical NetCDF file compliant with PredSea marine schemas.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import xarray as xr


def parse_vts_file(path: Path) -> dict[str, np.ndarray]:
    """Parse a single VTS XML structured grid shard and extract its arrays."""
    with open(path, "rb") as f:
        content = f.read()

    appended_tag = b'<AppendedData encoding="raw">'
    tag_idx = content.find(appended_tag)
    if tag_idx == -1:
        raise ValueError(f"Could not find AppendedData tag in {path}")

    # Parse XML header portion
    xml_header = content[:tag_idx] + appended_tag + b"\n  </AppendedData>\n</VTKFile>"
    root = ET.fromstring(xml_header)

    piece = root.find(".//Piece")
    if piece is None:
        raise ValueError(f"No Piece element found in {path}")

    extent_str = piece.attrib["Extent"]
    extent = [int(x) for x in extent_str.split()]
    nx = extent[1] - extent[0] + 1
    ny = extent[3] - extent[2] + 1
    nz = extent[5] - extent[4] + 1
    num_points = nx * ny * nz

    # Parse DataArrays and offsets
    data_arrays = {}
    for da in root.findall(".//DataArray"):
        name = da.attrib.get("Name") or "coordinates"
        offset = int(da.attrib["offset"])
        num_components = int(da.attrib.get("NumberOfComponents", 1))
        data_arrays[name] = {
            "offset": offset,
            "num_components": num_components,
            "type": da.attrib["type"]
        }

    # Extract binary payload
    underscore_idx = content.find(b"_", tag_idx + len(appended_tag))
    if underscore_idx == -1:
        raise ValueError(f"Could not find underscore start of binary block in {path}")
    binary_start = underscore_idx + 1

    arrays = {"_extent": extent}
    for name, spec in data_arrays.items():
        offset = spec["offset"]
        num_components = spec["num_components"]

        # Read 4-byte block size header
        header_bytes = content[binary_start + offset : binary_start + offset + 4]
        block_size = int.from_bytes(header_bytes, "little")

        # Read actual data bytes
        data_bytes = content[binary_start + offset + 4 : binary_start + offset + 4 + block_size]
        arr = np.frombuffer(data_bytes, dtype=np.float32)

        # Reshape to 3D grid: (nz, ny, nx) or (ny, nx, num_components)
        if num_components > 1:
            arr = arr.reshape(ny, nx, num_components)
        else:
            arr = arr.reshape(ny, nx)

        arrays[name] = arr

    return arrays


def convert_vtk_to_netcdf(
    results_dir: Path,
    output_path: Path,
) -> None:
    """Stitch parallel VTK shards and write a unified, canonical NetCDF file."""
    # 1. Load run metadata from input_manifest.json
    manifest_path = results_dir / "input_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing input_manifest.json under {results_dir}")
    manifest = json.loads(manifest_path.read_text())

    start_time_str = manifest["start_time"]
    start_time = dt.datetime.fromisoformat(start_time_str)
    nx_expected = manifest["grid"]["nx"]
    ny_expected = manifest["grid"]["ny"]

    print(f"Loaded manifest: region={manifest.get('region_id')}, grid={nx_expected}x{ny_expected}, start={start_time}")

    # 2. Parse master swan_output.pvd to locate timesteps
    pvd_path = results_dir / "swan_output.pvd"
    if not pvd_path.exists():
        raise FileNotFoundError(f"Missing swan_output.pvd under {results_dir}")

    pvd_tree = ET.parse(pvd_path)
    datasets = pvd_tree.findall(".//DataSet")
    if not datasets:
        raise ValueError("No DataSet elements found in PVD file")

    print(f"Found {len(datasets)} simulation timesteps in PVD index.")

    # 3. Pre-allocate unified grids for each variable and timestep
    nt = len(datasets)
    times = [start_time + dt.timedelta(hours=i) for i in range(nt)]

    # NaN-filled, not zero-filled: zero is a plausible-looking (but wrong)
    # coordinate value, so a stitching gap left at the zero default would
    # silently corrupt the coordinate arrays instead of being detectable.
    # NaN can't be mistaken for a real longitude/latitude, so any tile that
    # never gets written stays visibly unpopulated.
    grid_lon = np.full((ny_expected, nx_expected), np.nan, dtype=np.float32)
    grid_lat = np.full((ny_expected, nx_expected), np.nan, dtype=np.float32)
    grid_hsig = np.zeros((nt, ny_expected, nx_expected), dtype=np.float32)
    grid_tp = np.zeros((nt, ny_expected, nx_expected), dtype=np.float32)
    grid_dir = np.zeros((nt, ny_expected, nx_expected), dtype=np.float32)
    grid_depth = np.zeros((nt, ny_expected, nx_expected), dtype=np.float32)

    # 4. Process each timestep
    for t_idx, ds in enumerate(datasets):
        pvts_rel_path = ds.attrib["file"]
        pvts_path = results_dir / pvts_rel_path
        if not pvts_path.exists():
            raise FileNotFoundError(f"PVTS file not found: {pvts_path}")

        print(f"Stitching timestep {t_idx} from: {pvts_rel_path}")

        # Parse PVTS XML metadata
        pvts_tree = ET.parse(pvts_path)
        pieces = pvts_tree.findall(".//Piece")
        if not pieces:
            raise ValueError(f"No Piece elements found in {pvts_path}")

        for piece in pieces:
            extent_str = piece.attrib["Extent"]
            extent = [int(x) for x in extent_str.split()]
            vts_rel_path = piece.attrib["Source"]

            # The relative path is relative to the pvts file's directory
            vts_path = pvts_path.parent / vts_rel_path
            if not vts_path.exists():
                raise FileNotFoundError(f"VTS shard not found: {vts_path}")

            # Parse binary VTS piece
            shard_data = parse_vts_file(vts_path)

            # Determine coordinates and slices
            # Extent represents index ranges: [x_min, x_max, y_min, y_max, z_min, z_max]
            x_slice = slice(extent[0], extent[1] + 1)
            y_slice = slice(extent[2], extent[3] + 1)

            # Extract coordinates (only need to populate coordinates once)
            if t_idx == 0:
                coords = shard_data["coordinates"]
                grid_lon[y_slice, x_slice] = coords[:, :, 0]
                grid_lat[y_slice, x_slice] = coords[:, :, 1]

            # Extract variable arrays
            grid_hsig[t_idx, y_slice, x_slice] = shard_data["Hsig"]
            grid_tp[t_idx, y_slice, x_slice] = shard_data["TPsmoo"]
            grid_dir[t_idx, y_slice, x_slice] = shard_data["Dir"]
            grid_depth[t_idx, y_slice, x_slice] = shard_data["Depth"]

    # 5. Clean up exception values for land/dry cells to pass physical range validations
    # SWAN writes exception value -9.0 for dry/land cell values.
    # We replace any values <= -9.0 with np.nan for physical wave fields to ensure correct ocean statistics.
    grid_hsig[grid_hsig <= -9.0] = np.nan
    grid_tp[grid_tp <= -9.0] = np.nan
    grid_dir[grid_dir <= -9.0] = np.nan


    # 6. Build 1D longitude and latitude coordinate arrays from regular grid
    # Previously this took a single edge slice (row 0 / column 0) on the
    # assumption that edge was always fully populated by some MPI piece's
    # tile. That assumption broke for gulf_of_lion_1km's regenerated
    # (500x200) grid: whichever piece(s) should have covered column 0 never
    # got stitched in, so grid_lat[:, 0] came out all-zero, and
    # validate_marine_output.py's coverage check then read that zero as a
    # real (wrong) latitude, failing with "output does not reach the
    # configured northern boundary" -- even though the actual wave data
    # (Hsig etc.) was correct.
    #
    # Since this is a regular lon/lat grid, every row shares one true
    # latitude and every column shares one true longitude, so any single
    # populated cell in a row/column is enough -- reducing with nanmax
    # (equivalent to nanmin here, since a real row/column's values agree)
    # picks up whichever piece actually wrote that row/column, regardless of
    # which specific row or column index happened to hold the data.
    lon_coords = np.nanmax(grid_lon, axis=0)
    lat_coords = np.nanmax(grid_lat, axis=1)
    if np.isnan(lon_coords).any() or np.isnan(lat_coords).any():
        raise ValueError(
            "Stitched coordinate grid has columns/rows with no data from any "
            "MPI piece -- the parallel VTK tiles do not fully cover the "
            f"expected {nx_expected}x{ny_expected} grid. This means an MPI "
            "piece's output is missing or its Extent didn't match the "
            "expected decomposition, not a downstream validation problem."
        )

    # Create xarray Dataset
    dataset = xr.Dataset(
        data_vars={
            "significant_wave_height": (
                ["time", "latitude", "longitude"],
                grid_hsig,
                {
                    "standard_name": "significant_wave_height",
                    "long_name": "Significant wave height",
                    "units": "m",
                },
            ),
            "peak_wave_period": (
                ["time", "latitude", "longitude"],
                grid_tp,
                {
                    "standard_name": "peak_wave_period",
                    "long_name": "Peak wave period",
                    "units": "s",
                },
            ),
            "mean_wave_direction": (
                ["time", "latitude", "longitude"],
                grid_dir,
                {
                    "standard_name": "mean_wave_direction",
                    "long_name": "Mean wave direction",
                    "units": "degrees",
                },
            ),
            "depth": (
                ["time", "latitude", "longitude"],
                grid_depth,
                {
                    "standard_name": "sea_floor_depth_below_sea_level",
                    "long_name": "Water depth",
                    "units": "m",
                },
            ),
        },
        coords={
            "time": (["time"], times, {"standard_name": "time", "long_name": "Time"}),
            "latitude": (
                ["latitude"],
                lat_coords,
                {"standard_name": "latitude", "long_name": "Latitude", "units": "degrees_north"},
            ),
            "longitude": (
                ["longitude"],
                lon_coords,
                {"standard_name": "longitude", "long_name": "Longitude", "units": "degrees_east"},
            ),
        },
        attrs={
            "title": "PredSea Native Marine Forecast - SWAN 1km",
            "institution": "PredSea System",
            "source": "SWAN version 41.51AB",
            "history": f"Converted from parallel VTK XML on {dt.datetime.now(dt.timezone.utc).isoformat()}",
            "conventions": "CF-1.8",
        },
    )

    # Save to canonical NetCDF
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_netcdf(output_path, format="NETCDF4")
    print(f"Successfully converted parallel VTK to NetCDF: {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-dir",
        type=Path,
        required=True,
        help="Directory containing SWAN parallel VTK outputs and input_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Target output canonical NetCDF file path",
    )
    args = parser.parse_args()

    try:
        convert_vtk_to_netcdf(args.results_dir, args.output)
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
