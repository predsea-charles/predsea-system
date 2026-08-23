#!/usr/bin/env python3
"""
scripts/hpc_cost_summary.py
Compiles a real HPC cost + validation-coverage summary from whatever real cost and
accuracy reports actually exist in GCS -- and says so honestly when they don't.

IMPORTANT HISTORY: the previous version of this script computed
`credit_consumed_usd` from constants explicitly labeled "Fixed known VM compile
costs" whenever a real per-run cost report wasn't found in GCS, and derived its
"proceed_to_production" recommendation from humanintheloop/scripts/model_comparison.py's
fabricated accuracy numbers. The report it produced (humanintheloop/hpc_cost_summary.json,
2026-06-26) was a placeholder dressed as a result, not a measurement.

This version:
  - Never invents a cost. If a real per-model cost report isn't in GCS, it says so
    (`status: "no_real_cost_recorded"`) instead of substituting a guessed constant.
  - Estimates cost from real VM runtime x published Spot price only when a real
    runtime record exists, and labels that estimate as an estimate, not an actual.
  - Reads accuracy coverage from the corrected model_comparison.py report shape
    (per-variable status: "compared" / "insufficient_sample_size" /
    "no_real_matched_pairs"), not a fabricated win percentage.
  - Never outputs "proceed_to_production" automatically. That recommendation
    requires a human judgment call once real validated coverage accumulates --
    this script reports status, not a green light.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

BUCKET_NAME = "predsea-hpc-outputs"

# GCP Spot list prices (europe-west1, USD/hour) as of 2026-06 -- these are published
# list prices, NOT a substitute for checking your actual billing console. Spot prices
# fluctuate; treat this table as a rough estimator only, and refresh it periodically.
SPOT_PRICE_USD_PER_HOUR = {
    "c2d-standard-16": 0.19,
    "c2d-standard-32": 0.38,
    "c2d-standard-56": 0.67,
    "c2d-highcpu-16": 0.17,
    "c3-highcpu-44": 0.62,
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate an honest PredSea HPC cost + validation-coverage report.")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help="Target run date (YYYY-MM-DD)")
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud project); used only if --bucket-project differs.")
    parser.add_argument("--no-upload", action="store_true", help="Skip uploading the report to GCS.")
    parser.add_argument("--output", default="hpc_cost_summary.json", help="Local path to write the report JSON to.")
    return parser.parse_args(argv)


def _bucket():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET_NAME)


def load_json_from_gcs(bucket, blob_path):
    """Loads a real report from GCS. Returns None (never a fabricated default) if it
    isn't there -- callers must handle the missing case explicitly and honestly."""
    blob = bucket.blob(blob_path)
    if not blob.exists():
        return None
    try:
        return json.loads(blob.download_as_text())
    except Exception as e:
        print(f"Warning: could not parse {blob_path}: {e}")
        return None


def estimate_cost_from_runtime(runtime_report):
    """Estimates a real cost from a real VM runtime record.

    Expected shape (written by whoever instruments the orchestrator/vm_startup.sh --
    this is not fabricated here, it's read from a report that must itself be real):
      {"vm_type": "c2d-standard-16", "wallclock_minutes": 87}
    Returns None if the shape isn't usable, rather than guessing.
    """
    if not runtime_report:
        return None
    vm_type = runtime_report.get("vm_type")
    wallclock_minutes = runtime_report.get("wallclock_minutes")
    if not vm_type or wallclock_minutes is None:
        return None
    price_per_hour = SPOT_PRICE_USD_PER_HOUR.get(vm_type)
    if price_per_hour is None:
        print(f"Warning: no known Spot price for vm_type '{vm_type}' -- add it to SPOT_PRICE_USD_PER_HOUR to estimate cost.")
        return None
    estimated_cost = round(price_per_hour * (float(wallclock_minutes) / 60.0), 2)
    return {
        "estimated_cost_usd": estimated_cost,
        "vm_type": vm_type,
        "wallclock_minutes": wallclock_minutes,
        "spot_price_usd_per_hour_used": price_per_hour,
        "is_estimate": True,
    }


def build_cost_section(bucket, date_str):
    """Real per-model cost, only from real reports. No fallback constants."""
    section = {}
    total_real_cost = 0.0
    any_real_cost = False

    # 2026-07-02: was ("wrf", "roms", "swan") -- but daily_orchestrator.py never runs
    # roms_forecast_ingestor.py; the real ocean models it runs are CROCO and NEMO
    # (see model_comparison.py's COMPARISON_SPECS for the same correction).
    for model in ("wrf", "croco", "nemo", "swan"):
        report = load_json_from_gcs(bucket, f"reports/{date_str}/{model}_cost.json")
        if report and report.get("actual_cost_usd") is not None:
            section[model] = {
                "status": "real",
                "actual_cost_usd": report["actual_cost_usd"],
                "wallclock_minutes": report.get("wallclock_minutes"),
            }
            total_real_cost += float(report["actual_cost_usd"])
            any_real_cost = True
            continue

        # No real cost report -- try to at least estimate from a real runtime record,
        # rather than substituting a hardcoded constant.
        runtime_report = load_json_from_gcs(bucket, f"reports/{date_str}/{model}_runtime.json")
        estimate = estimate_cost_from_runtime(runtime_report)
        if estimate:
            section[model] = {"status": "estimated_from_real_runtime", **estimate}
        else:
            section[model] = {
                "status": "no_real_cost_recorded",
                "message": (
                    f"No real cost or runtime record found at reports/{date_str}/{model}_cost.json "
                    f"or {model}_runtime.json. Not substituting a guess -- run the model and record "
                    "actual VM runtime, or pull the real number from the GCP billing console."
                ),
            }

    benchmark_report = load_json_from_gcs(bucket, "reports/vm-benchmark.json")
    if isinstance(benchmark_report, list) and benchmark_report:
        section["vm_benchmarking"] = {
            "status": "real",
            "total_cost_usd": round(sum(item.get("benchmark_cost_usd", 0.0) for item in benchmark_report), 2),
        }
        total_real_cost += section["vm_benchmarking"]["total_cost_usd"]
        any_real_cost = True
    else:
        section["vm_benchmarking"] = {"status": "no_real_cost_recorded"}

    return section, (round(total_real_cost, 2) if any_real_cost else None), any_real_cost


def build_accuracy_section(bucket, date_str):
    """Reads real validation coverage from the corrected model_comparison.py report
    shape. Never derives a win percentage -- that comparison isn't wired up yet
    (model_comparison.py currently validates the own model against real buoys, not
    against a real CMEMS forecast pull -- see its docstring)."""
    accuracy_report = load_json_from_gcs(bucket, f"reports/{date_str}/accuracy_comparison.json")

    if not accuracy_report:
        return {"status": "no_accuracy_report_found", "compared_variables": []}, "no_real_run_yet"

    if accuracy_report.get("status") in ("no_forecast_data", "no_nearby_stations"):
        return {
            "status": accuracy_report["status"],
            "message": accuracy_report.get("message"),
            "compared_variables": [],
        }, "no_real_run_yet"

    # accuracy_comparison.json nests by variable -> provider (e.g. current_speed has
    # both predsea_croco and predsea_nemo, since the orchestrator runs both models)
    compared_variables = []
    total_pairs = 0
    for variable, by_provider in (accuracy_report.get("variables") or {}).items():
        for provider, details in (by_provider or {}).items():
            total_pairs += 1
            if details.get("status") == "compared":
                compared_variables.append(
                    {
                        "variable": variable,
                        "own_model_provider": provider,
                        "metrics_own_model": details.get("metrics_own_model"),
                        "stations_used": details.get("stations_used"),
                    }
                )

    total_variables = total_pairs
    if not compared_variables:
        recommendation = "insufficient_real_validation_data"
    elif len(compared_variables) < total_variables:
        recommendation = "partial_real_validation_gather_more_data"
    else:
        recommendation = "full_real_validation_review_with_team"

    return {
        "status": "real",
        "compared_variables": compared_variables,
        "variables_with_real_comparison": len(compared_variables),
        "variables_total": total_variables,
    }, recommendation


def main(argv=None):
    args = parse_args(argv)
    date_str = args.date
    bucket = _bucket()

    cost_breakdown, total_real_cost_usd, any_real_cost = build_cost_section(bucket, date_str)
    accuracy_summary, recommendation = build_accuracy_section(bucket, date_str)

    report = {
        "report_date": date_str,
        "data_source": "real" if any_real_cost else "no_real_cost_recorded",
        "credit_consumed_usd": total_real_cost_usd,
        "cost_breakdown": cost_breakdown,
        "accuracy_summary": accuracy_summary,
        # Deliberately not "proceed_to_production" -- see module docstring. A human
        # (you) decides that once real validated coverage looks good enough, this
        # script only ever reports status.
        "recommendation": recommendation,
        "recommendation_note": (
            "This recommendation reflects data coverage only, not a go/no-go "
            "judgment. 'proceed_to_production' is intentionally never auto-generated."
        ),
    }

    print(f"HPC cost + validation summary compiled for {date_str}. Recommendation: {recommendation}")
    if not any_real_cost:
        print("No real cost data was found -- credit_consumed_usd is null, not a guessed default.")

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote report to {args.output}")

    if not args.no_upload:
        blob_path = f"reports/{date_str}/hpc_cost_summary.json"
        bucket.blob(blob_path).upload_from_filename(args.output)
        print(f"Uploaded report to gs://{BUCKET_NAME}/{blob_path}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
