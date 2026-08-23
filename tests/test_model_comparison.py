"""
Tests for the corrected humanintheloop/scripts/model_comparison.py.

These tests deliberately avoid needing real GCP credentials or the google-cloud-*
packages: every function under test here operates on plain Python data (lists of
dicts) that stand in for BigQuery query results, so the *matching and reporting
logic* can be verified without a live BigQuery connection. The actual BigQuery
queries (fetch_forecast_rows / fetch_observation_rows / fetch_station_catalog) are
thin and intentionally not re-tested here -- they only build query parameters -- but
their output shape (list of dict-like rows) is exactly what these tests feed in.

No test in this file uses np.random or any other synthetic-data generator to fake a
result -- fixtures here are small, fixed, hand-picked numbers so every expected value
below was computed by hand, not sampled.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "humanintheloop" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "humanintheloop"))

import model_comparison as mc  # noqa: E402


def test_comparison_specs_only_name_operational_model_providers():
    providers = {spec["own_provider"] for spec in mc.COMPARISON_SPECS}
    assert "predsea_roms" not in providers
    assert {"predsea_wrf", "predsea_croco", "predsea_nemo", "predsea_swan"} <= providers


def _t(hour, minute=0):
    return datetime(2026, 7, 2, hour, minute, tzinfo=timezone.utc)


def test_compute_metrics_returns_none_for_fewer_than_two_points():
    assert mc.compute_metrics([1.0], [1.1]) is None
    assert mc.compute_metrics([], []) is None


def test_compute_metrics_hand_computed_values():
    # own = obs + [1, -1, 1, -1] -> bias 0, mae 1, rmse 1
    own = [11.0, 9.0, 11.0, 9.0]
    obs = [10.0, 10.0, 10.0, 10.0]
    metrics = mc.compute_metrics(own, obs)
    assert metrics["sample_size"] == 4
    assert metrics["bias"] == 0.0
    assert metrics["mae"] == 1.0
    assert metrics["rmse"] == 1.0
    # obs is constant so correlation is undefined (std_o == 0) -> None, not fabricated as 1.0
    assert metrics["correlation"] is None


def test_compute_metrics_ignores_nan_pairs():
    own = [10.0, float("nan"), 12.0]
    obs = [10.0, 5.0, 10.0]
    metrics = mc.compute_metrics(own, obs)
    assert metrics["sample_size"] == 2
    assert metrics["bias"] == 1.0  # (0 + 2) / 2


def test_nearest_station_finds_closest_within_radius():
    stations = [
        {"station_id": "far", "latitude": 41.0, "longitude": 5.0},
        {"station_id": "near", "latitude": 39.51, "longitude": 2.63},
    ]
    station, distance_nm = mc.nearest_station(39.5, 2.62, stations, max_distance_nm=25.0)
    assert station["station_id"] == "near"
    assert distance_nm < 5.0


def test_nearest_station_returns_none_outside_radius():
    stations = [{"station_id": "far", "latitude": 41.0, "longitude": 5.0}]
    station, distance_nm = mc.nearest_station(39.5, 2.62, stations, max_distance_nm=5.0)
    assert station is None
    assert distance_nm is None


def test_match_forecast_points_to_stations_skips_unmatched_points():
    stations = [{"station_id": "palma_buoy", "station_name": "Palma", "latitude": 39.48, "longitude": 2.62}]
    forecast_rows = [
        {"variable": "wave_height", "value": 1.1, "target_time_utc": _t(6), "latitude": 39.48, "longitude": 2.62},
        {"variable": "wave_height", "value": 1.3, "target_time_utc": _t(7), "latitude": 60.0, "longitude": 60.0},  # nowhere near any station
    ]
    annotated, matched_ids = mc.match_forecast_points_to_stations(forecast_rows, stations, max_distance_nm=10.0)
    assert matched_ids == {"palma_buoy"}
    assert len(annotated) == 1  # the far-away point was dropped, not force-matched
    assert annotated[0]["matched_station_id"] == "palma_buoy"


def test_pair_forecasts_with_observations_respects_time_tolerance():
    annotated_rows = [
        {
            "variable": "wave_height",
            "provider": "predsea_swan",
            "value": 1.2,
            "target_time_utc": _t(6, 0),
            "matched_station_id": "palma_buoy",
        },
        {
            "variable": "wave_height",
            "provider": "predsea_swan",
            "value": 1.5,
            "target_time_utc": _t(9, 0),
            "matched_station_id": "palma_buoy",
        },
    ]
    observation_rows = [
        # within 30 min of the 06:00 forecast -> should pair
        {"station_id": "palma_buoy", "variable": "wave_height", "value": 1.0, "observed_at_utc": _t(6, 20)},
        # more than 30 min from the 09:00 forecast -> should NOT pair
        {"station_id": "palma_buoy", "variable": "wave_height", "value": 2.0, "observed_at_utc": _t(9, 45)},
    ]
    pairs = mc.pair_forecasts_with_observations(annotated_rows, observation_rows, time_tolerance_minutes=30)
    key = ("wave_height", "predsea_swan")
    assert pairs[key]["own"] == [1.2]
    assert pairs[key]["obs"] == [1.0]


def test_pair_forecasts_keeps_croco_and_nemo_separate():
    # Both models sample the same point/time and both report current_speed --
    # they must not be pooled into one bucket just because the variable matches.
    annotated_rows = [
        {"variable": "current_speed", "provider": "predsea_croco", "value": 0.5, "target_time_utc": _t(6, 0), "matched_station_id": "palma_buoy"},
        {"variable": "current_speed", "provider": "predsea_nemo", "value": 0.9, "target_time_utc": _t(6, 0), "matched_station_id": "palma_buoy"},
    ]
    observation_rows = [
        {"station_id": "palma_buoy", "variable": "current_speed", "value": 0.6, "observed_at_utc": _t(6, 5)},
    ]
    pairs = mc.pair_forecasts_with_observations(annotated_rows, observation_rows, time_tolerance_minutes=30)
    assert pairs[("current_speed", "predsea_croco")]["own"] == [0.5]
    assert pairs[("current_speed", "predsea_nemo")]["own"] == [0.9]


def test_build_comparison_report_reports_insufficient_data_honestly():
    # Only 2 real matched pairs, below the default minimum sample size of 5 --
    # the report must say so, not compute a metric anyway.
    pairs_by_variable_provider = {
        ("wave_height", "predsea_swan"): {"own": [1.1, 1.3], "obs": [1.0, 1.2], "stations": {"palma_buoy"}},
    }
    report = mc.build_comparison_report(pairs_by_variable_provider, min_sample_size=5, target_date="2026-07-02")
    assert report["data_source"] == "real"
    assert report["variables"]["wave_height"]["predsea_swan"]["status"] == "insufficient_sample_size"
    assert "metrics_own_model" not in report["variables"]["wave_height"]["predsea_swan"]
    # Untouched (variable, provider) pairs must say plainly there was no real matched data.
    assert report["variables"]["wind_speed"]["predsea_wrf"]["status"] == "no_real_matched_pairs"
    assert report["summary"]["variable_provider_pairs_with_real_comparison"] == 0


def test_build_comparison_report_reports_real_metrics_when_enough_data():
    pairs_by_variable_provider = {
        ("wave_height", "predsea_swan"): {
            "own": [1.1, 1.3, 0.9, 1.0, 1.2],
            "obs": [1.0, 1.2, 1.0, 0.9, 1.1],
            "stations": {"palma_buoy"},
        }
    }
    report = mc.build_comparison_report(pairs_by_variable_provider, min_sample_size=5, target_date="2026-07-02")
    assert report["variables"]["wave_height"]["predsea_swan"]["status"] == "compared"
    assert report["variables"]["wave_height"]["predsea_swan"]["metrics_own_model"]["sample_size"] == 5
    assert report["summary"]["variable_provider_pairs_with_real_comparison"] == 1
    # own_beats_cmems must never appear -- that comparison isn't wired up yet, and
    # must not be guessed at.
    assert "own_beats_cmems" not in report["variables"]["wave_height"]["predsea_swan"]


def test_build_comparison_report_keeps_croco_and_nemo_as_separate_entries():
    pairs_by_variable_provider = {
        ("current_speed", "predsea_croco"): {"own": [0.5] * 5, "obs": [0.6] * 5, "stations": {"palma_buoy"}},
    }
    report = mc.build_comparison_report(pairs_by_variable_provider, min_sample_size=5, target_date="2026-07-02")
    assert report["variables"]["current_speed"]["predsea_croco"]["status"] == "compared"
    # NEMO wasn't given any real pairs here, so it must independently say so --
    # never inherit CROCO's result.
    assert report["variables"]["current_speed"]["predsea_nemo"]["status"] == "no_real_matched_pairs"


if __name__ == "__main__":
    # Allow running these tests without pytest installed (e.g. in a sandbox with no
    # network access) by calling every test_* function directly.
    failures = 0
    for name, fn in sorted(vars(sys.modules[__name__]).items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS: {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL: {name}: {e}")
    if failures:
        print(f"\n{failures} test(s) failed.")
        sys.exit(1)
    print("\nAll tests passed.")
