import numpy as np
from pathlib import Path
from scripts.prepare_ww3_bounc import render_ww3_bounc_nml

def test_render_ww3_bounc_nml():
    start = np.datetime64("2026-08-05T00:00:00")
    end = np.datetime64("2026-08-06T00:00:00")
    nml = render_ww3_bounc_nml(start, end, "alboran_1km")

    assert "&BOUNC_NML" in nml
    assert "BOUNC%TIMESTART   = '20260805 000000'" in nml
    assert "BOUNC%TIMESTOP    = '20260806 000000'" in nml
    assert "BOUNC%TYPE        = 'PAR'" in nml
