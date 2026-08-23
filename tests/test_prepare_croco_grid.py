from __future__ import annotations

import numpy as np
import xarray as xr

from scripts.prepare_croco_grid import (
    CROCO_REQUIRED_GRID_VARIABLES,
    build_grid,
    crop_bathymetry_to_bbox,
    smooth_bathymetry,
)


def test_smooth_bathymetry_enforces_rx0():
    depth = np.array([[10.0, 1000.0], [10.0, 1000.0]])
    wet = np.ones_like(depth, dtype=bool)
    smoothed, iterations, achieved = smooth_bathymetry(
        depth, wet, maximum_rx0=0.2
    )
    assert iterations > 0
    assert achieved <= 0.2 + 1e-12
    assert smoothed.min() > 10.0


def test_build_grid_creates_complete_croco_staggered_grid():
    longitude, latitude = np.meshgrid(
        np.array([1.0, 1.01, 1.02, 1.03]),
        np.array([38.0, 38.01, 38.02]),
    )
    bathymetry = xr.Dataset(
        {
            "bathy": (("y", "x"), [[0.0, 20.0, 30.0, 40.0]] * 3),
            "nav_lon": (("y", "x"), longitude),
            "nav_lat": (("y", "x"), latitude),
        }
    )

    grid, report = build_grid(bathymetry)

    assert grid.sizes["eta_rho"] == 3
    assert grid.sizes["xi_rho"] == 4
    assert grid.sizes["xi_u"] == 3
    assert grid.sizes["eta_v"] == 2
    assert set(
        (
            "h",
            "hraw",
            "mask_rho",
            "mask_u",
            "mask_v",
            "mask_psi",
            "pm",
            "pn",
            "angle",
            "f",
        )
    ) <= set(grid.variables)
    assert report["maximum_rx0"] <= 0.2 + 1e-12
    assert report["wet_cell_count"] == 9
    assert 0.0 <= report["changed_wet_cell_fraction"] <= 1.0
    assert report["maximum_wet_cell_deepening_m"] >= 0.0
    assert CROCO_REQUIRED_GRID_VARIABLES <= set(grid.variables)
    assert float(grid["xl"].item()) > 0.0
    assert float(grid["el"].item()) > 0.0
    assert report["xl_m"] == float(grid["xl"].item())
    assert report["el_m"] == float(grid["el"].item())


def test_crop_bathymetry_to_region_bbox():
    longitude, latitude = np.meshgrid(
        np.arange(-2.0, 3.0, 0.5),
        np.arange(35.0, 43.0, 0.5),
    )
    source = xr.Dataset(
        {
            "bathy": (("y", "x"), np.full(longitude.shape, 100.0)),
            "nav_lon": (("y", "x"), longitude),
            "nav_lat": (("y", "x"), latitude),
        }
    )
    cropped = crop_bathymetry_to_bbox(
        source,
        {
            "longitude_min": -1.0,
            "longitude_max": 1.0,
            "latitude_min": 37.0,
            "latitude_max": 39.0,
        },
    )
    assert cropped["bathy"].shape == (5, 5)
    assert float(cropped["nav_lon"].min()) == -1.0
    assert float(cropped["nav_lon"].max()) == 1.0
    assert float(cropped["nav_lat"].min()) == 37.0
    assert float(cropped["nav_lat"].max()) == 39.0


def test_crop_bathymetry_rejects_uncovered_bbox():
    longitude, latitude = np.meshgrid(np.arange(3.0), np.arange(3.0))
    source = xr.Dataset(
        {
            "bathy": (("y", "x"), np.full((3, 3), 100.0)),
            "nav_lon": (("y", "x"), longitude),
            "nav_lat": (("y", "x"), latitude),
        }
    )
    with np.testing.assert_raises_regex(ValueError, "does not cover"):
        crop_bathymetry_to_bbox(
            source,
            {
                "longitude_min": -6.0,
                "longitude_max": -1.0,
                "latitude_min": 35.0,
                "latitude_max": 37.5,
            },
        )
