from pathlib import Path

import numpy as np
import xarray as xr

from processing.gfs_interpreter import get_gfs_summary


def test_get_gfs_summary_reads_nearest_10m_wind_from_netcdf(tmp_path):
    gfs_path = tmp_path / "gfs_sample.nc"
    dataset = xr.Dataset(
        data_vars={
            "u10": (("time", "latitude", "longitude"), np.array([[[-4.0, -2.0], [-1.0, -3.0]]])),
            "v10": (("time", "latitude", "longitude"), np.array([[[-1.0, -1.0], [-2.0, -4.0]]])),
            "msl": (("time", "latitude", "longitude"), np.array([[[101000.0, 101100.0], [101200.0, 101300.0]]])),
        },
        coords={
            "time": np.array(["2026-04-29T18:00:00"], dtype="datetime64[ns]"),
            "latitude": np.array([39.25, 39.75]),
            "longitude": np.array([3.0, 3.5]),
        },
    )
    dataset.to_netcdf(gfs_path)

    summary = get_gfs_summary(39.7, 3.45, "2026-04-29T18:00:00Z", gfs_path)

    assert summary["model"] == "gfs"
    assert summary["wind_knots"] == 10
    assert summary["direction"] == "NE"
    assert summary["location"]["nearest_grid"]["lat"] == 39.75
    assert summary["location"]["nearest_grid"]["lon"] == 3.5
    assert summary["metrics"]["u10_mps"] == -3.0
    assert summary["metrics"]["v10_mps"] == -4.0
    assert summary["metrics"]["pressure_hpa"] == 1013.0
