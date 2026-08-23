"""
Tests for the corrected humanintheloop/scripts/hpc_cost_summary.py.

Uses a tiny fake GCS bucket/blob stand-in instead of google-cloud-storage, so these
tests run without credentials or network access. The point of every test here is to
prove the script never substitutes a hardcoded constant for a missing real report --
that was exactly the bug being fixed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "humanintheloop" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "humanintheloop"))

import hpc_cost_summary as hcs  # noqa: E402


class _FakeBlob:
    def __init__(self, content=None):
        self._content = content

    def exists(self):
        return self._content is not None

    def download_as_text(self):
        return json.dumps(self._content)


class _FakeBucket:
    def __init__(self, contents: dict):
        # contents maps blob_path -> python object (or None for "not present")
        self._contents = contents

    def blob(self, blob_path):
        return _FakeBlob(self._contents.get(blob_path))


def test_estimate_cost_from_runtime_known_vm():
    estimate = hcs.estimate_cost_from_runtime({"vm_type": "c2d-standard-16", "wallclock_minutes": 60})
    assert estimate["estimated_cost_usd"] == hcs.SPOT_PRICE_USD_PER_HOUR["c2d-standard-16"]
    assert estimate["is_estimate"] is True


def test_estimate_cost_from_runtime_missing_price_returns_none_not_a_guess():
    assert hcs.estimate_cost_from_runtime({"vm_type": "totally-unknown-vm", "wallclock_minutes": 60}) is None


def test_estimate_cost_from_runtime_missing_report_returns_none():
    assert hcs.estimate_cost_from_runtime(None) is None
    assert hcs.estimate_cost_from_runtime({}) is None


def test_build_cost_section_with_no_real_reports_never_fabricates():
    bucket = _FakeBucket({})  # nothing exists in GCS
    section, total_cost, any_real = hcs.build_cost_section(bucket, "2026-07-02")
    assert any_real is False
    assert total_cost is None  # not 0.0, not a guessed constant -- genuinely unknown
    for model in ("wrf", "croco", "nemo", "swan"):
        assert section[model]["status"] == "no_real_cost_recorded"


def test_build_cost_section_uses_real_cost_when_present():
    bucket = _FakeBucket(
        {
            "reports/2026-07-02/wrf_cost.json": {"actual_cost_usd": 1.23, "wallclock_minutes": 30},
        }
    )
    section, total_cost, any_real = hcs.build_cost_section(bucket, "2026-07-02")
    assert any_real is True
    assert section["wrf"]["status"] == "real"
    assert total_cost == 1.23
    # croco/nemo/swan still have no real report -> must stay honest, not inherit wrf's number
    assert section["croco"]["status"] == "no_real_cost_recorded"


def test_build_cost_section_estimates_from_real_runtime_when_no_actual_cost():
    bucket = _FakeBucket(
        {
            "reports/2026-07-02/swan_runtime.json": {"vm_type": "c2d-standard-16", "wallclock_minutes": 30},
        }
    )
    section, total_cost, any_real = hcs.build_cost_section(bucket, "2026-07-02")
    assert section["swan"]["status"] == "estimated_from_real_runtime"
    assert section["swan"]["is_estimate"] is True
    # An estimate does not count as a confirmed real cost total.
    assert any_real is False
    assert total_cost is None


def test_build_accuracy_section_no_report_recommends_no_real_run_yet():
    bucket = _FakeBucket({})
    accuracy_summary, recommendation = hcs.build_accuracy_section(bucket, "2026-07-02")
    assert accuracy_summary["status"] == "no_accuracy_report_found"
    assert recommendation == "no_real_run_yet"


def test_build_accuracy_section_never_says_proceed_to_production():
    # Even with full real comparison coverage, the recommendation vocabulary must
    # never include "proceed_to_production" -- that judgment call belongs to a human.
    # Note the nested variable -> provider shape (matches model_comparison.py's
    # corrected report, since e.g. current_speed has both predsea_croco and
    # predsea_nemo entries).
    accuracy_report = {
        "data_source": "real",
        "variables": {
            "wave_height": {
                "predsea_swan": {
                    "status": "compared",
                    "metrics_own_model": {"rmse": 0.2, "bias": 0.05, "correlation": 0.9, "mae": 0.15, "sample_size": 20},
                    "stations_used": ["palma_buoy"],
                }
            }
        },
    }
    bucket = _FakeBucket({"reports/2026-07-02/accuracy_comparison.json": accuracy_report})
    accuracy_summary, recommendation = hcs.build_accuracy_section(bucket, "2026-07-02")
    assert accuracy_summary["status"] == "real"
    assert accuracy_summary["variables_with_real_comparison"] == 1
    assert recommendation != "proceed_to_production"
    assert "proceed_to_production" not in (recommendation or "")


if __name__ == "__main__":
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
