from pathlib import Path

import pytest
import xarray as xr

from scripts.run_marine_simulation import stage_cmems_forcing


def test_staged_cmems_requires_complete_three_dimensional_forcing(tmp_path: Path):
    cached = tmp_path / "cmems_ocean_forcing.nc"
    xr.Dataset(
        {
            "uo": (("time", "latitude", "longitude"), [[[1.0]]]),
            "vo": (("time", "latitude", "longitude"), [[[1.0]]]),
        }
    ).to_netcdf(cached)

    with pytest.raises(ValueError, match="missing variables"):
        stage_cmems_forcing(cached, tmp_path / "work")


def test_staged_cmems_accepts_complete_three_dimensional_forcing(tmp_path: Path):
    cached = tmp_path / "cmems_ocean_forcing.nc"
    xr.Dataset(
        {
            "uo": (("time", "depth", "latitude", "longitude"), [[[[1.0]]]]),
            "vo": (("time", "depth", "latitude", "longitude"), [[[[1.0]]]]),
            "thetao": (("time", "depth", "latitude", "longitude"), [[[[20.0]]]]),
            "so": (("time", "depth", "latitude", "longitude"), [[[[38.0]]]]),
            "zos": (("time", "latitude", "longitude"), [[[0.0]]]),
        }
    ).to_netcdf(cached)
    work = tmp_path / "work"
    work.mkdir()

    staged = stage_cmems_forcing(cached, work)

    assert staged == work / "cmems_ocean_forcing.nc"
    assert staged.stat().st_size == cached.stat().st_size
