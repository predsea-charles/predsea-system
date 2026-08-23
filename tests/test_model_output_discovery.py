from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xarray as xr

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from model_output_discovery import is_model_output_name, validate_model_output


def test_wps_intermediates_are_never_model_outputs():
    met_em = "predictions/2026-07-16/runs/run/wrf/met_em.d02.2026-07-16_00:00:00.nc"
    for model in ("wrf", "croco", "nemo", "swan"):
        assert not is_model_output_name(met_em, model)


def test_model_names_are_stage_specific():
    assert is_model_output_name("run/wrf/wrfout_d02_2026-07-16_00:00:00", "wrf")
    assert is_model_output_name("run/roms/croco_his.nc", "croco")
    assert is_model_output_name("run/nemo/nemo_output.nc", "nemo")
    assert is_model_output_name("run/swan/swan_out.nc", "swan")
    assert not is_model_output_name("run/wrf/wrfout_d02_2026-07-16_00:00:00", "swan")
    assert not is_model_output_name("run/swan/swan_out.nc", "nemo")


def test_content_signature_rejects_met_em_for_every_model(tmp_path):
    path = tmp_path / "met_em.d02.nc"
    xr.Dataset(
        {"PRES": (("Time", "south_north", "west_east"), np.ones((1, 2, 2)))},
    ).to_netcdf(path)

    for model in ("wrf", "croco", "nemo", "swan"):
        valid, reason = validate_model_output(path, model)
        assert not valid
        assert reason.startswith("missing ")


def test_wrf_content_signature_requires_coordinates(tmp_path):
    path = tmp_path / "wrfout.nc"
    xr.Dataset(
        {
            "XLAT": (("Time", "y", "x"), np.ones((1, 2, 2))),
            "XLONG": (("Time", "y", "x"), np.ones((1, 2, 2))),
        }
    ).to_netcdf(path)

    assert validate_model_output(path, "wrf") == (True, "ok")
