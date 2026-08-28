from pathlib import Path

import numpy as np

from scripts.prepare_ww3_forcing import render_ww3_ounf_nml
from scripts.prepare_ww3_wind_from_wrf import render_ww3_ounf_nml as render_wrf_ww3_ounf_nml


def test_ounf_namelist_targets_shel_native_grid_output_contract():
    start = np.datetime64("2026-08-04T00:00:00")
    end = np.datetime64("2026-08-04T06:00:00")

    for rendered in (render_ww3_ounf_nml(start, end), render_wrf_ww3_ounf_nml(start, end)):
        assert "out_grd.ww3" in rendered
        assert "FIELD%TIMESTART  = '20260804 000000'" in rendered
        assert "FIELD%TIMESTRIDE = '3600'" in rendered
        assert "FIELD%TIMECOUNT  = '7'" in rendered
        assert "FIELD%LIST       = 'HS DIR SPR WND DTD FC CFX'" in rendered
        assert "FILE%NETCDF = 4" in rendered


def test_aws_runner_requires_ounf_namelist():
    runner = Path("scripts/aws_ww3_runner.py").read_text()
    assert '"ww3_ounf.nml"' in runner
