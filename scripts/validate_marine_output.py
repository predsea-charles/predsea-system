#!/usr/bin/env python3
"""Fail-closed validation for native PredSea marine model output."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import xarray as xr


ALIASES = {
    "latitude": ("latitude", "lat", "nav_lat", "lat_rho", "LAT"),
    "longitude": ("longitude", "lon", "nav_lon", "lon_rho", "LON"),
    "time": ("time", "Time", "ocean_time", "time_counter"),
    "significant_wave_height": (
        "hs",
        "hsign",
        "significant_wave_height",
        "swh",
        "hsig",
        "Hsign",
    ),
    "peak_wave_period": ("tps", "tp", "tpp", "peak_wave_period", "RTpeak"),
    "mean_wave_direction": ("dir", "mwd", "pwd", "wave_direction", "theta0", "deg"),
    "eastward_current": ("u", "uo", "u_current", "eastward_sea_water_velocity"),
    "northward_current": ("v", "vo", "v_current", "northward_sea_water_velocity"),
    "sea_surface_temperature": ("temp", "thetao", "sst", "sea_surface_temperature"),
    "sea_surface_salinity": ("salt", "so", "sss", "sea_surface_salinity"),
    "sea_surface_height": ("zeta", "zos", "ssh", "sea_surface_height"),
}


def _first_existing(dataset: xr.Dataset, names: Iterable[str]) -> str | None:
    return next((name for name in names if name in dataset.variables), None)


def _apply_matching_mask(dataset: xr.Dataset, da: xr.DataArray) -> xr.DataArray:
    """Apply land mask only if mask dimensions match or are a subset of da dimensions."""
    mask_candidates = (
        ("mask_u", "mask_v", "mask_rho", "mask")
        if ("xi_u" in da.dims or "eta_v" in da.dims)
        else ("mask_rho", "mask_u", "mask_v", "mask")
    )
    for mask_name in mask_candidates:
        if mask_name in dataset.variables:
            mask_da = dataset[mask_name]
            if set(mask_da.dims).issubset(set(da.dims)):
                return da.where(mask_da == 1)
    return da


def _finite_stats(data: xr.DataArray) -> dict[str, float | int]:
    values = np.asarray(data.values)
    finite = np.isfinite(values)

    # Check if this is a 3D+ time-series spatial field: (time, ...)
    if values.ndim >= 3:
        # Identify land mask: coordinates that are ALWAYS NaN across all times
        is_nan = ~finite
        land_mask = np.all(is_nan, axis=0)
        wet_mask = ~land_mask

        # Calculate size of the wet ocean domain across all timesteps
        ntime = values.shape[0]
        wet_count = int(np.sum(wet_mask) * ntime)
        finite_count = int(finite.sum())

        result: dict[str, float | int] = {
            "count": wet_count,
            "finite_count": finite_count,
            "finite_fraction": finite_count / wet_count if wet_count else 1.0,
        }
    else:
        # Fallback for 1D/2D coords or metrics without time dim
        count = int(values.size)
        finite_count = int(finite.sum())
        result = {
            "count": count,
            "finite_count": finite_count,
            "finite_fraction": finite_count / count if count else 0.0,
        }

    if finite_count:
        finite_values = values[finite]
        result.update(
            minimum=float(np.min(finite_values)),
            maximum=float(np.max(finite_values)),
            mean=float(np.mean(finite_values)),
        )
    return result


def validate(
    output_path: Path,
    model: str,
    region_path: Path,
    forecast_hours: int,
) -> dict:
    region = json.loads(region_path.read_text())
    model_spec = region["models"][model]
    expected_timestamps = forecast_hours // region["output_interval_hours"] + 1
    errors: list[str] = []
    warnings: list[str] = []
    variables: dict[str, dict] = {}

    with xr.open_dataset(output_path) as dataset:
        lat_name = _first_existing(dataset, ALIASES["latitude"])
        lon_name = _first_existing(dataset, ALIASES["longitude"])
        time_name = _first_existing(dataset, ALIASES["time"])

        if not lat_name or not lon_name:
            errors.append("missing latitude/longitude coordinates")
        if not time_name:
            errors.append("missing forecast time coordinate")
            timestamp_count = 0
        else:
            timestamp_count = int(dataset[time_name].size)
            if timestamp_count != expected_timestamps:
                errors.append(
                    f"expected {expected_timestamps} timestamps, found {timestamp_count}"
                )
            try:
                raw_time = dataset[time_name].values
                if np.issubdtype(raw_time.dtype, np.floating) or np.issubdtype(raw_time.dtype, np.integer):
                    units = getattr(dataset[time_name], "units", "").lower()
                    if "day" in units:
                        deltas = np.diff(raw_time) * 86400.0
                    else:
                        deltas = np.diff(raw_time)
                    expected_seconds = region["output_interval_hours"] * 3600
                    if not np.allclose(deltas, expected_seconds, rtol=1e-2):
                        errors.append("forecast timestamps are not uniformly hourly")
                else:
                    decoded = np.asarray(raw_time).astype("datetime64[ns]")
                    if decoded.size > 1:
                        deltas = np.diff(decoded).astype("timedelta64[s]").astype(np.int64)
                        expected_seconds = region["output_interval_hours"] * 3600
                        if not np.all(deltas == expected_seconds):
                            errors.append("forecast timestamps are not uniformly hourly")
            except (TypeError, ValueError):
                warnings.append("time coordinate could not be decoded for interval validation")

        bbox = region["bbox"]
        coverage: dict[str, float] = {}
        if lat_name and lon_name:
            lat_stats = _finite_stats(dataset[lat_name])
            lon_stats = _finite_stats(dataset[lon_name])
            if not lat_stats["finite_count"] or not lon_stats["finite_count"]:
                errors.append("latitude/longitude coordinates contain no finite values")
            else:
                coverage = {
                    "latitude_min": float(lat_stats["minimum"]),
                    "latitude_max": float(lat_stats["maximum"]),
                    "longitude_min": float(lon_stats["minimum"]),
                    "longitude_max": float(lon_stats["maximum"]),
                }
                tolerance = 0.05
                if coverage["latitude_min"] > bbox["latitude_min"] + tolerance:
                    errors.append("output does not reach the configured southern boundary")
                if coverage["latitude_max"] < bbox["latitude_max"] - tolerance:
                    errors.append("output does not reach the configured northern boundary")
                if coverage["longitude_min"] > bbox["longitude_min"] + tolerance:
                    errors.append("output does not reach the configured western boundary")
                if coverage["longitude_max"] < bbox["longitude_max"] - tolerance:
                    errors.append("output does not reach the configured eastern boundary")

        for canonical_name in model_spec["required_variables"]:
            source_name = _first_existing(dataset, ALIASES[canonical_name])
            if not source_name:
                errors.append(f"missing required variable {canonical_name}")
                continue
            da = dataset[source_name]
            if "s_rho" in da.dims:
                da = da.isel(s_rho=-1)
            da = _apply_matching_mask(dataset, da)
            stats = _finite_stats(da)
            variables[canonical_name] = {"source_name": source_name, **stats}
            
            vals = np.asarray(da.values)
            nans = np.isnan(vals)
            if np.any(nans):
                nan_indices = np.argwhere(nans)
                first_idx = tuple(nan_indices[0])
                print(f"❌ [VALIDATION] FAILED FIELD: {canonical_name} ({source_name}) | Total NaNs: {np.sum(nans)} | First NaN index (t,k,j,i): {first_idx}")

            if stats["finite_fraction"] < 0.90:
                errors.append(
                    f"{canonical_name} finite fraction is {stats['finite_fraction']:.3f}, below 0.90"
                )
            if stats["finite_count"]:
                lower, upper = model_spec["physical_ranges"][canonical_name]
                if stats["minimum"] < lower or stats["maximum"] > upper:
                    errors.append(
                        f"{canonical_name} range [{stats['minimum']}, {stats['maximum']}] "
                        f"exceeds [{lower}, {upper}]"
                    )

        # Optional fields are still reported and range-checked when present.
        for canonical_name, bounds in model_spec["physical_ranges"].items():
            if canonical_name in variables:
                continue
            source_name = _first_existing(dataset, ALIASES[canonical_name])
            if not source_name:
                continue
            da = dataset[source_name]
            if "s_rho" in da.dims:
                da = da.isel(s_rho=-1)
            da = _apply_matching_mask(dataset, da)
            stats = _finite_stats(da)
            variables[canonical_name] = {"source_name": source_name, **stats}
            if stats["finite_count"] and (
                stats["minimum"] < bounds[0] or stats["maximum"] > bounds[1]
            ):
                errors.append(f"optional variable {canonical_name} is outside physical bounds")

    return {
        "schema_version": "predsea.marine_validation.v1",
        "validated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "succeeded" if not errors else "failed",
        "model": model,
        "region_id": region["region_id"],
        "output_path": str(output_path),
        "output_size_bytes": output_path.stat().st_size,
        "forecast_hours": forecast_hours,
        "expected_timestamps": expected_timestamps,
        "timestamp_count": timestamp_count,
        "coverage": coverage,
        "variables": variables,
        "warnings": warnings,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("swan", "croco"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--region", type=Path, required=True)
    parser.add_argument("--forecast-hours", type=int, required=True)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate(args.output, args.model, args.region, args.forecast_hours)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n")
    print(rendered)
    return 0 if report["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
