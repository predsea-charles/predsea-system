#!/usr/bin/env python3
"""
measure_rate.py (v2) — pull CROCO timestep log lines from CloudWatch and
compute seconds/step across multiple windows.

Changes from v1 (per agent findings on the live baseline run):
  - Windows are now specified in actual MODEL STEPS (--window-model-steps),
    not print-line count. The script auto-detects the log's print interval
    (e.g. CROCO printing every 10 steps) and converts internally, so you
    never have to guess how many print lines a window corresponds to.
  - Leading non-monotonic lines (e.g. initialization/header diagnostics that
    reset step-like columns before real timestep logging begins) are
    detected and dropped BEFORE anomaly detection, so they no longer get
    misreported as mid-run restarts.

Requires: boto3.

Usage:
    python3 measure_rate.py \\
        --log-group /predsea/croco \\
        --log-stream batch/default/<container-id> \\
        --region eu-west-1 \\
        --timestep-seconds 90 \\
        --window-model-steps 200
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

try:
    import boto3
except ImportError:
    print("ERROR: boto3 is required. Install with: pip install boto3", file=sys.stderr)
    sys.exit(1)

STEP_LINE_RE = re.compile(r"^\s*(\d+)\s+([\d.eE+-]+)\s+(.*)$")


def fetch_all_events(client, log_group: str, log_stream: str, limit_per_call: int = 10000):
    events = []
    kwargs = dict(
        logGroupName=log_group,
        logStreamName=log_stream,
        limit=limit_per_call,
        startFromHead=True,
    )
    next_token = None
    while True:
        if next_token:
            kwargs["nextToken"] = next_token
        resp = client.get_log_events(**kwargs)
        batch = resp.get("events", [])
        if not batch:
            break
        events.extend(batch)
        new_token = resp.get("nextForwardToken")
        if new_token == next_token:
            break
        next_token = new_token
    return events


def parse_step_lines(events):
    parsed = []
    for ev in events:
        msg = ev.get("message", "")
        m = STEP_LINE_RE.match(msg)
        if not m:
            continue
        try:
            step = int(m.group(1))
        except ValueError:
            continue
        parsed.append((ev["timestamp"], step))
    return parsed


def drop_init_prefix(parsed):
    """
    Drop a leading prefix of lines that isn't part of the real, monotonic
    step sequence (e.g. header/init diagnostics that print a different kind
    of counter before real timestep logging starts, like a '32 -> 0' reset).

    Heuristic: find the first index i such that steps[i:i+5] (or all
    remaining, if fewer than 5 left) are strictly increasing. Drop everything
    before that index. This assumes the *real* logging, once it starts, is
    consistently monotonic — which matches CROCO's normal timestep output.
    """
    n = len(parsed)
    for i in range(n):
        lookahead = parsed[i:i + 5]
        steps = [s for _, s in lookahead]
        if len(steps) < 2:
            continue
        if all(steps[j] < steps[j + 1] for j in range(len(steps) - 1)):
            if i > 0:
                print(f"NOTE: dropped {i} leading line(s) before real monotonic "
                      f"timestep logging appeared to start (treated as "
                      f"initialization/header output, not a restart).", file=sys.stderr)
            return parsed[i:]
    return parsed


def detect_print_interval(parsed):
    """Find the most common step-to-step delta, e.g. 10 if CROCO prints every 10 steps."""
    diffs = [b - a for (_, a), (_, b) in zip(parsed, parsed[1:]) if b > a]
    if not diffs:
        return 1
    return Counter(diffs).most_common(1)[0][0]


def detect_anomalies(parsed):
    warnings = []
    for i in range(1, len(parsed)):
        prev_ts, prev_step = parsed[i - 1]
        ts, step = parsed[i]
        if step <= prev_step:
            warnings.append(
                f"Step number did not increase (prev={prev_step} at index {i-1}, "
                f"now={step} at index {i}) — possible restart, duplicate log "
                f"stream, or a log line the parser mis-tokenized."
            )
        gap_s = (ts - prev_ts) / 1000.0
        if gap_s > 300:
            warnings.append(
                f"Large time gap ({gap_s:.1f}s) between step {prev_step} and {step} "
                f"— possible stall, checkpoint pause, or job restart."
            )
    return warnings


def windowed_rates(parsed, window_model_steps: int, print_interval: int):
    """
    Compute seconds/step over consecutive windows of `window_model_steps`
    real model steps (converted to however many print-lines that spans,
    given the detected print_interval).
    """
    lines_per_window = max(1, round(window_model_steps / print_interval))
    results = []
    i = 0
    while i + lines_per_window < len(parsed):
        start_ts, start_step = parsed[i]
        end_ts, end_step = parsed[i + lines_per_window]
        wall_s = (end_ts - start_ts) / 1000.0
        n_steps = end_step - start_step
        if n_steps <= 0:
            i += lines_per_window
            continue
        s_per_step = wall_s / n_steps
        results.append((start_step, end_step, wall_s, n_steps, s_per_step))
        i += lines_per_window
    return results, lines_per_window


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-group", required=True)
    ap.add_argument("--log-stream", required=True)
    ap.add_argument("--region", default="eu-west-1")
    ap.add_argument("--window-model-steps", type=int, default=200,
                     help="Real model steps per measurement window (default: 200). "
                          "Converted internally to however many print-lines that "
                          "spans, based on the log's detected print interval.")
    ap.add_argument("--timestep-seconds", type=float, default=None,
                     help="If given, project total 72h wall time using this dt.")
    args = ap.parse_args()

    client = boto3.client("logs", region_name=args.region)

    print(f"Fetching events from {args.log_group} / {args.log_stream} ...", file=sys.stderr)
    events = fetch_all_events(client, args.log_group, args.log_stream)
    print(f"Fetched {len(events)} raw log events.", file=sys.stderr)

    parsed = parse_step_lines(events)
    print(f"Parsed {len(parsed)} timestep-shaped lines.", file=sys.stderr)

    if len(parsed) < 2:
        print("ERROR: fewer than 2 timestep lines found. Check a raw sample line "
              "against STEP_LINE_RE if this is unexpected.", file=sys.stderr)
        return 1

    parsed = drop_init_prefix(parsed)
    if len(parsed) < 2:
        print("ERROR: after dropping the initialization prefix, fewer than 2 "
              "usable lines remain. The job may not have reached steady-state "
              "logging yet.", file=sys.stderr)
        return 1

    print_interval = detect_print_interval(parsed)
    print(f"Detected print interval: every {print_interval} model step(s).", file=sys.stderr)

    warnings = detect_anomalies(parsed)
    if warnings:
        print("\n⚠️  ANOMALIES DETECTED — treat rate measurements with caution:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
        print("", file=sys.stderr)

    windows, lines_per_window = windowed_rates(parsed, args.window_model_steps, print_interval)
    print(f"(Window of {args.window_model_steps} model steps = {lines_per_window} "
          f"print-line(s) at the detected interval.)\n", file=sys.stderr)

    if not windows:
        available_steps = (len(parsed) - 1) * print_interval
        print(f"ERROR: not enough data for even one window of "
              f"{args.window_model_steps} model steps. Only ~{available_steps} "
              f"model steps of log are available so far. Either lower "
              f"--window-model-steps or let the job run longer.", file=sys.stderr)
        return 1

    print(f"\n{'Steps':>18} | {'Wall (s)':>10} | {'n_steps':>8} | {'s/step':>8}")
    print("-" * 52)
    for start_step, end_step, wall_s, n_steps, s_per_step in windows:
        print(f"{start_step:>8} -> {end_step:<7} | {wall_s:>10.1f} | {n_steps:>8} | {s_per_step:>8.4f}")

    last_start, last_end, last_wall, last_n, last_rate = windows[-1]
    print(f"\nLast window rate (use this one — most likely to reflect settled "
          f"performance, discard earlier windows as warm-up): {last_rate:.4f} s/step")

    if args.timestep_seconds:
        total_steps_72h = 72 * 3600 / args.timestep_seconds
        projected_wall_h = (total_steps_72h * last_rate) / 3600
        print(f"\nAt timestep_seconds={args.timestep_seconds}:")
        print(f"  Steps for a 72h forecast: {total_steps_72h:.0f}")
        print(f"  Projected 72h wall time:  {projected_wall_h:.2f} hours "
              f"({projected_wall_h/24:.2f} days)")
    else:
        print("\n(Pass --timestep-seconds to also see a projected 72h wall-time estimate.)")

    if warnings:
        print("\n⚠️  Reminder: anomalies were detected above. Investigate before "
              "treating this measurement as final.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
