#!/usr/bin/env python3
"""Fetch and fail-closed validate ECMWF 10 m wind for a SWAN forecast."""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import xarray as xr
from ecmwf.opendata import Client


def source_steps(forecast_hours: int) -> list[int]:
    """Return forecast steps actually published by ECMWF Open Data."""
    steps = list(range(0, forecast_hours + 1, 3))
    if steps[-1] != forecast_hours:
        steps.append(forecast_hours)
    return steps


def expected_times(run_date: str, forecast_hours: int) -> np.ndarray:
    start = np.datetime64(f"{run_date}T00:00:00", "ns")
    return np.asarray(
        [start + np.timedelta64(step, "h") for step in source_steps(forecast_hours)],
        dtype="datetime64[ns]",
    )


def validate_wind(path: Path, run_date: str, forecast_hours: int) -> dict:
    """Decode both components and require exact published-step coverage."""
    expected = expected_times(run_date, forecast_hours)
    report: dict[str, object] = {"path": str(path), "expected_times": len(expected)}
    for short_name, variable in (("10u", "u10"), ("10v", "v10")):
        with xr.open_dataset(
            path,
            engine="cfgrib",
            backend_kwargs={
                "filter_by_keys": {"shortName": short_name},
                "indexpath": "",
            },
        ) as dataset:
            if variable not in dataset:
                raise ValueError(f"{path.name} is missing {short_name}/{variable}")
            values = dataset[variable].load()
            observed = np.asarray(dataset.valid_time.values).reshape(-1).astype(
                "datetime64[ns]"
            )
            if not np.array_equal(observed, expected):
                raise ValueError(
                    f"{short_name} coverage does not match the exact ECMWF source window: "
                    f"observed {observed[0] if observed.size else 'empty'}.."
                    f"{observed[-1] if observed.size else 'empty'} "
                    f"({observed.size} times), expected {expected[0]}..{expected[-1]} "
                    f"({expected.size} times)"
                )
            finite = np.isfinite(values.values)
            if not finite.all():
                raise ValueError(
                    f"{short_name} contains {finite.size - int(finite.sum())} non-finite values"
                )
            report[short_name] = {
                "times": int(observed.size),
                "minimum": float(values.min()),
                "maximum": float(values.max()),
            }
    return report


def fetch_wind(run_date: str, forecast_hours: int, target: Path) -> dict:
    """Download a small, native ECMWF forecast bulletin and validate all data."""
    if forecast_hours <= 0 or forecast_hours > 120:
        raise ValueError("forecast_hours must be between 1 and 120")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    partial.unlink(missing_ok=True)
    try:
        Client().retrieve(
            date=run_date,
            time=0,
            type="fc",
            levtype="sfc",
            param=["10u", "10v"],
            # ECMWF Open Data IFS publishes these surface forecast fields at
            # three-hour steps. SWAN preparation interpolates them to the
            # operational hourly timeline after this source-level validation.
            step=source_steps(forecast_hours),
            target=str(partial),
        )
        report = validate_wind(partial, run_date, forecast_hours)
        partial.replace(target)
        report["path"] = str(target)
        return report
    finally:
        partial.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--forecast-hours", required=True, type=int)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        report = validate_wind(args.target, args.run_date, args.forecast_hours)
    else:
        report = fetch_wind(args.run_date, args.forecast_hours, args.target)
    print(f"ECMWF_SWAN_WIND_VALIDATED {report}")


if __name__ == "__main__":
    main()
