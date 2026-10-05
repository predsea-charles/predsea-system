#!/usr/bin/env python3

from pathlib import Path

import numpy as np
import xarray as xr


INPUT = Path(
    "assets/static_grids/western_mediterranean_1km_bathymetry_swan.nc"
)

OUTPUT = Path(
    "assets/static_grids/western_mediterranean_2km_bathymetry_swan.nc"
)

# Two source cells -> approximately 2 km.
FACTOR = 2


def main():
    with xr.open_dataset(INPUT) as ds:
        depth = ds["depth"]

        if depth.dims != ("latitude", "longitude"):
            raise ValueError(
                f"Unexpected depth dimensions: {depth.dims}"
            )

        ny, nx = depth.shape

        # Use complete 2x2 blocks only.
        trimmed_ny = (ny // FACTOR) * FACTOR
        trimmed_nx = (nx // FACTOR) * FACTOR

        depth = depth.isel(
            latitude=slice(0, trimmed_ny),
            longitude=slice(0, trimmed_nx),
        )

        values = np.asarray(depth.values, dtype=np.float64)

        # Treat numerical near-zero noise as land.
        values[values < 0.01] = 0.0

        # Reshape into 2x2 blocks.
        blocks = values.reshape(
            trimmed_ny // FACTOR,
            FACTOR,
            trimmed_nx // FACTOR,
            FACTOR,
        )

        # A 2x2 cell is water only when at least half of the
        # source cells are water. This avoids letting a single
        # coastal water pixel expand the coastline into land.
        water = blocks > 0.0
        water_count = water.sum(axis=(1, 3))

        # Average only actual water depths.
        positive_sum = np.where(water, blocks, 0.0).sum(axis=(1, 3))

        positive_count = water_count

        output = np.zeros_like(positive_sum)

        np.divide(
            positive_sum,
            positive_count,
            out=output,
            where=positive_count > 0,
        )

        output[water_count < 2] = 0.0

        # Coordinates: use the center of each 2x2 source block.
        lat = np.asarray(depth["latitude"].values)
        lon = np.asarray(depth["longitude"].values)

        lat_out = lat.reshape(-1, FACTOR)[:, :].mean(axis=1)
        lon_out = lon.reshape(-1, FACTOR)[:, :].mean(axis=1)

        # Trim coordinates to match the complete blocks.
        lat_out = lat_out[: output.shape[0]]
        lon_out = lon_out[: output.shape[1]]

        result = xr.Dataset(
            {
                "depth": (
                    ("latitude", "longitude"),
                    output.astype(np.float32),
                )
            },
            coords={
                "latitude": lat_out.astype(np.float32),
                "longitude": lon_out.astype(np.float32),
            },
            attrs={
                "title": "PredSea WW3 Western Mediterranean 2 km Bathymetry",
                "source": ds.attrs.get(
                    "source",
                    "Derived from western_mediterranean_1km_bathymetry_swan.nc",
                ),
                "resolution_deg": float(
                    np.mean(np.diff(lon_out))
                ),
                "derived_from": str(INPUT),
                "downsampling_factor": FACTOR,
                "land_rule": "2x2 source block requires at least 2 water cells",
                "near_zero_threshold_m": 0.01,
            },
        )

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        result.to_netcdf(OUTPUT)

        print(f"Wrote: {OUTPUT}")
        print(f"Shape: {result.sizes['latitude']} x {result.sizes['longitude']}")
        print(
            f"Latitude: {float(lat_out[0])} -> {float(lat_out[-1])}"
        )
        print(
            f"Longitude: {float(lon_out[0])} -> {float(lon_out[-1])}"
        )
        print(
            f"Spacing longitude: {float(np.mean(np.diff(lon_out)))} deg"
        )
        print(
            f"Spacing latitude: {float(np.mean(np.diff(lat_out)))} deg"
        )

        d = output
        print(f"Ocean cells: {np.count_nonzero(d > 0)}")
        print(f"Land cells:  {np.count_nonzero(d == 0)}")
        print(f"Min ocean depth: {d[d > 0].min():.3f} m")
        print(f"Max depth:       {d.max():.3f} m")


if __name__ == "__main__":
    main()
