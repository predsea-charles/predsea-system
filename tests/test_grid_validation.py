from __future__ import annotations

import json

import numpy as np
import pytest
import xarray as xr

import scripts.grid_validation as grid_validation


def _write_region(tmp_path, region_id="test_1km"):
    region_dir = tmp_path / "regions"
    region_dir.mkdir()
    (region_dir / f"{region_id}.json").write_text(
        json.dumps(
            {
                "bbox": {
                    "longitude_min": 0.5,
                    "longitude_max": 5.5,
                    "latitude_min": 37.5,
                    "latitude_max": 41.5,
                }
            }
        ),
        encoding="utf-8",
    )
    return region_dir


def _write_grid(tmp_path, lon_bounds=(0.5, 5.5), lat_bounds=(37.5, 41.5), **attrs):
    lon, lat = np.meshgrid(
        np.linspace(*lon_bounds, 6),
        np.linspace(*lat_bounds, 5),
    )
    path = tmp_path / "grid.nc"
    xr.Dataset(
        {
            "lon_rho": (("eta_rho", "xi_rho"), lon),
            "lat_rho": (("eta_rho", "xi_rho"), lat),
        },
        attrs=attrs,
    ).to_netcdf(path)
    return path


def test_grid_geography_requires_all_bbox_edges_to_match(tmp_path, monkeypatch):
    monkeypatch.setattr(grid_validation, "REGION_CONFIG_DIR", _write_region(tmp_path))
    path = _write_grid(tmp_path)

    grid_validation.validate_grid_matches_region(path, "test_1km")


def test_grid_geography_rejects_smaller_grid_inside_region(tmp_path, monkeypatch):
    monkeypatch.setattr(grid_validation, "REGION_CONFIG_DIR", _write_region(tmp_path))
    path = _write_grid(tmp_path, lon_bounds=(1.0, 5.0), lat_bounds=(38.0, 41.0))

    with pytest.raises(ValueError, match="do not match expected bbox"):
        grid_validation.validate_grid_matches_region(path, "test_1km")


def test_grid_geography_rejects_non_finite_coordinates(tmp_path, monkeypatch):
    monkeypatch.setattr(grid_validation, "REGION_CONFIG_DIR", _write_region(tmp_path))
    path = _write_grid(tmp_path)
    with xr.open_dataset(path) as source:
        grid = source.load()
    grid["lon_rho"][0, 0] = np.nan
    grid.to_netcdf(path, mode="w")

    with pytest.raises(ValueError, match="non-empty and finite"):
        grid_validation.validate_grid_matches_region(path, "test_1km")


def test_grid_geography_rejects_declared_region_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(grid_validation, "REGION_CONFIG_DIR", _write_region(tmp_path))
    path = _write_grid(tmp_path, region_id="other_1km")

    with pytest.raises(ValueError, match="region_id mismatch"):
        grid_validation.validate_grid_matches_region(path, "test_1km")
