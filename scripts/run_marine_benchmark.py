#!/usr/bin/env python3
"""Run one bounded native marine model benchmark and record honest telemetry."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from validate_marine_output import validate


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("swan", "croco"), required=True)
    parser.add_argument("--region", type=Path, required=True)
    parser.add_argument("--forecast-hours", type=int, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument(
        "--hourly-compute-cost-usd",
        type=float,
        help="Current full-VM hourly price; omitted means cost remains unpriced.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command after --, for example: -- mpirun -np 16 swan.exe INPUT",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise SystemExit("A model command is required after --")
    executable = shutil.which(command[0]) if "/" not in command[0] else command[0]
    if not executable or not Path(executable).exists():
        raise SystemExit(f"Model command is not executable: {command[0]}")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = args.report_dir / f"{args.model}.stdout.log"
    stderr_path = args.report_dir / f"{args.model}.stderr.log"
    started = dt.datetime.now(dt.timezone.utc)
    start_monotonic = time.monotonic()
    initial_disk_bytes = directory_bytes(args.work_dir)
    timed_out = False

    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        process = subprocess.Popen(
            command,
            cwd=args.work_dir,
            stdout=stdout,
            stderr=stderr,
            env=os.environ.copy(),
        )
        try:
            return_code = process.wait(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return_code = 124

    elapsed_seconds = time.monotonic() - start_monotonic
    completed = dt.datetime.now(dt.timezone.utc)
    final_disk_bytes = directory_bytes(args.work_dir)
    validation = None
    errors: list[str] = []
    if return_code != 0:
        errors.append(f"model command exited with {return_code}")
    if timed_out:
        errors.append(f"model exceeded timeout of {args.timeout_seconds}s")
    if not args.output.exists() or args.output.stat().st_size == 0:
        errors.append(f"expected model output is missing or empty: {args.output}")
    else:
        validation = validate(
            args.output,
            args.model,
            args.region,
            args.forecast_hours,
        )
        errors.extend(validation["errors"])

    hourly_cost = args.hourly_compute_cost_usd
    compute_cost = (
        round(hourly_cost * elapsed_seconds / 3600.0, 6)
        if hourly_cost is not None
        else None
    )
    report = {
        "schema_version": "predsea.marine_benchmark.v1",
        "status": "succeeded" if not errors else "failed",
        "measurement_type": "real_execution",
        "model": args.model,
        "region": str(args.region),
        "forecast_hours": args.forecast_hours,
        "command": command,
        "started_at_utc": started.isoformat(),
        "completed_at_utc": completed.isoformat(),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "return_code": return_code,
        "timed_out": timed_out,
        "host_cpu_count": os.cpu_count(),
        "work_dir_initial_bytes": initial_disk_bytes,
        "work_dir_final_bytes": final_disk_bytes,
        "work_dir_growth_bytes": final_disk_bytes - initial_disk_bytes,
        "output_size_bytes": args.output.stat().st_size if args.output.exists() else 0,
        "pricing": {
            "hourly_compute_cost_usd": hourly_cost,
            "measured_compute_cost_usd": compute_cost,
            "storage_and_network_cost_included": False,
        },
        "validation": validation,
        "logs": {
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        },
        "errors": errors,
    }
    report_path = args.report_dir / f"{args.model}_benchmark.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    marker = args.report_dir / ("SUCCESS" if not errors else "FAILURE")
    marker.write_text(
        json.dumps(
            {
                "model": args.model,
                "status": report["status"],
                "report": str(report_path),
            },
            sort_keys=True,
        )
        + "\n"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
