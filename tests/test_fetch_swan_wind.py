import numpy as np

from scripts.fetch_swan_wind import expected_times, source_steps


def test_source_steps_follow_ecmwf_three_hour_publication():
    assert source_steps(24) == [0, 3, 6, 9, 12, 15, 18, 21, 24]


def test_source_steps_include_non_multiple_horizon_endpoint():
    assert source_steps(10) == [0, 3, 6, 9, 10]


def test_expected_times_match_source_steps():
    observed = expected_times("2026-07-20", 6)
    expected = np.asarray(
        ["2026-07-20T00:00:00", "2026-07-20T03:00:00", "2026-07-20T06:00:00"],
        dtype="datetime64[ns]",
    )
    assert np.array_equal(observed, expected)
