from pathlib import Path

from simulation.marine.croco.prepare_croco_in import render


TEMPLATE = Path("simulation/marine/croco/croco.in.balearic")


def test_renders_six_hour_gate_from_single_horizon(tmp_path):
    result = render(
        TEMPLATE.read_text(),
        start_date="2026-07-20",
        forecast_hours=6,
        work_dir=tmp_path,
    )

    assert "360      60      30      10" in result
    assert "2026-07-20 00:00:00" in result
    assert "2026-07-20 06:00:00" in result
    assert f"{tmp_path}/croco_blk.nc" in result
    assert f"{tmp_path}/croco_bry.nc" in result
    assert "boundary: filename\n" + f"    {tmp_path}/croco_clm.nc" not in result
    assert f"{tmp_path}/croco_his.nc" in result


def test_renders_conservative_twenty_second_gate_with_hourly_history(tmp_path):
    result = render(
        TEMPLATE.read_text(),
        start_date="2026-07-20",
        forecast_hours=6,
        work_dir=tmp_path,
        timestep_seconds=20,
    )

    assert "1080      20      30      10" in result
    assert "T      180     0" in result


def test_rejects_duration_above_operational_limit():
    try:
        render(TEMPLATE.read_text(), start_date="2026-07-20", forecast_hours=121, work_dir=Path("/work"))
    except ValueError as exc:
        assert "between 1 and 120" in str(exc)
    else:
        raise AssertionError("invalid horizon must be rejected")
