from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from scripts.prepare_croco_bulk_forcing import _wrf_timestamp, build_bulk_forcing


def test_decodes_netcdf_fixed_width_byte_timestamp():
    raw = np.array([b"2026-07-16T00:00:00"], dtype="S19")

    assert _wrf_timestamp(raw) == "2026-07-16T00:00:00"


def _write_grid(path: Path) -> None:
    xr.Dataset(
        {
            "lon_rho": (("eta_rho", "xi_rho"), [[2.0, 2.5], [2.0, 2.5]]),
            "lat_rho": (("eta_rho", "xi_rho"), [[39.0, 39.0], [39.5, 39.5]]),
        }
    ).to_netcdf(path)


def _write_wrf(path: Path, stamp: str, rain: float) -> None:
    shape = (1, 2, 2)
    times = np.array([[char.encode() for char in stamp]], dtype="S1")
    xr.Dataset(
        {
            "Times": (("Time", "DateStrLen"), times),
            "XLAT": (("Time", "south_north", "west_east"), [[[39.0, 39.0], [39.5, 39.5]]]),
            "XLONG": (("Time", "south_north", "west_east"), [[[2.0, 2.5], [2.0, 2.5]]]),
            "U10": (("Time", "south_north", "west_east"), np.full(shape, 5.0)),
            "V10": (("Time", "south_north", "west_east"), np.full(shape, -2.0)),
            "T2": (("Time", "south_north", "west_east"), np.full(shape, 293.15)),
            "Q2": (("Time", "south_north", "west_east"), np.full(shape, 0.008)),
            "PSFC": (("Time", "south_north", "west_east"), np.full(shape, 101325.0)),
            "SWDOWN": (("Time", "south_north", "west_east"), np.full(shape, 300.0)),
            "GLW": (("Time", "south_north", "west_east"), np.full(shape, 350.0)),
            "RAINC": (("Time", "south_north", "west_east"), np.zeros(shape)),
            "RAINNC": (("Time", "south_north", "west_east"), np.full(shape, rain)),
        }
    ).to_netcdf(path)


def test_builds_real_croco_bulk_forcing(tmp_path):
    grid = tmp_path / "grid.nc"
    first = tmp_path / "wrfout_00.nc"
    second = tmp_path / "wrfout_01.nc"
    output = tmp_path / "croco_blk.nc"
    _write_grid(grid)
    _write_wrf(first, "2026-07-20_00:00:00", 0.0)
    _write_wrf(second, "2026-07-20_01:00:00", 3.6)

    result = build_bulk_forcing(
        [first, second],
        grid,
        output,
        start_time=np.datetime64("2026-07-20T00:00:00"),
        forecast_hours=1,
    )

    assert output.exists()
    assert result.attrs["source"] == "PredSea WRF"
    assert result.sizes["bulk_time"] == 3
    assert set(("uwnd", "vwnd", "tair", "rhum", "prate", "radlw_in", "radsw")) <= set(result)
    assert "radlw" not in result
    assert np.isclose(float(result["prate"].isel(bulk_time=1).mean()), 1.0e-6)
    assert 0.0 < float(result["rhum"].mean()) <= 100.0


def test_rejects_non_wrf_netcdf(tmp_path):
    grid = tmp_path / "grid.nc"
    bad = tmp_path / "met_em.nc"
    _write_grid(grid)
    xr.Dataset({"PRES": (("y", "x"), np.ones((2, 2)))}).to_netcdf(bad)

    try:
        build_bulk_forcing([bad], grid, tmp_path / "out.nc")
    except ValueError as exc:
        assert "not WRF output" in str(exc)
    else:
        raise AssertionError("non-WRF input must be rejected")


def test_rejects_wrong_wrf_timeline(tmp_path):
    grid = tmp_path / "grid.nc"
    first = tmp_path / "wrfout_00.nc"
    second = tmp_path / "wrfout_02.nc"
    _write_grid(grid)
    _write_wrf(first, "2026-07-20_00:00:00", 0.0)
    _write_wrf(second, "2026-07-20_02:00:00", 0.0)

    try:
        build_bulk_forcing(
            [first, second],
            grid,
            tmp_path / "out.nc",
            start_time=np.datetime64("2026-07-20T00:00:00"),
            forecast_hours=1,
        )
    except ValueError as exc:
        assert "exact requested hourly timeline" in str(exc)
    else:
        raise AssertionError("non-hourly or wrong-cycle WRF input must be rejected")
