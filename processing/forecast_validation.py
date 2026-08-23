from __future__ import annotations

from math import sqrt
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

import xarray as xr

from ingestion.observations_client import Observation
from processing.gfs_interpreter import get_gfs_summary
from processing.mariner_interpreter import get_captain_summary


SUPPORTED_VARIABLES = {
    "wind_knots": ("wind_knots",),
    "pressure_hpa": ("metrics", "pressure_hpa"),
}


def compare_forecast_distributions(
    observations: list[Observation],
    wrfout_paths: list[str | Path],
    time: str | None,
    variable: str = "wind_knots",
) -> dict[str, Any]:
    if variable not in SUPPORTED_VARIABLES:
        supported = ", ".join(sorted(SUPPORTED_VARIABLES))
        raise ValueError(f"Unsupported validation variable {variable!r}. Supported: {supported}.")

    observed_values = [_observation_value(observation, variable) for observation in observations]
    observed_values = [value for value in observed_values if value is not None]
    if not observed_values:
        raise ValueError(f"No observations contain {variable!r}.")

    domains = [
        _score_domain(
            observations=observations,
            wrfout_path=Path(wrfout_path),
            time=time,
            variable=variable,
        )
        for wrfout_path in wrfout_paths
    ]
    best = min(domains, key=_score_sort_key)

    return {
        "variable": variable,
        "observation_count": len(observed_values),
        "observed_distribution": _distribution(observed_values),
        "domains": domains,
        "best_domain": {
            "domain": best["domain"],
            "mae": best["mae"],
            "rmse": best["rmse"],
            "bias": best["bias"],
            "ks_statistic": best["ks_statistic"],
        },
    }


def compare_gfs_to_predsea(
    observations: list[Observation],
    gfs_path: str | Path,
    wrfout_path: str | Path,
    time: str | None,
    variable: str = "wind_knots",
) -> dict[str, Any]:
    if variable not in SUPPORTED_VARIABLES:
        supported = ", ".join(sorted(SUPPORTED_VARIABLES))
        raise ValueError(f"Unsupported validation variable {variable!r}. Supported: {supported}.")

    observed_values = [_observation_value(observation, variable) for observation in observations]
    observed_values = [value for value in observed_values if value is not None]
    if not observed_values:
        raise ValueError(f"No observations contain {variable!r}.")

    models = [
        _score_model(
            model_name="gfs",
            observations=observations,
            forecast_getter=lambda observation: get_gfs_summary(
                observation.lat,
                observation.lon,
                time,
                gfs_path,
            ),
            variable=variable,
            source=Path(gfs_path),
        ),
        _score_model(
            model_name=f"predsea_wrf_{_domain_label(Path(wrfout_path))}",
            observations=observations,
            forecast_getter=lambda observation: get_captain_summary(
                observation.lat,
                observation.lon,
                time,
                wrfout_path,
            ),
            variable=variable,
            source=Path(wrfout_path),
            domain_bounds=_wrf_domain_bounds(Path(wrfout_path)),
        ),
    ]
    best = min(models, key=_score_sort_key)

    return {
        "variable": variable,
        "observation_count": len(observed_values),
        "observed_distribution": _distribution(observed_values),
        "models": models,
        "best_model": {
            "model": best["model"],
            "mae": best["mae"],
            "rmse": best["rmse"],
            "bias": best["bias"],
            "ks_statistic": best["ks_statistic"],
        },
    }


def _score_domain(
    observations: list[Observation],
    wrfout_path: Path,
    time: str | None,
    variable: str,
) -> dict[str, Any]:
    pairs = []
    matches = []
    skipped = []
    domain_bounds = _wrf_domain_bounds(wrfout_path)
    for observation in observations:
        observed = _observation_value(observation, variable)
        if observed is None:
            continue

        if not _point_inside_bounds(observation.lat, observation.lon, domain_bounds):
            skipped.append(_skipped_observation(observation, "outside_domain"))
            continue

        summary = get_captain_summary(
            lat=observation.lat,
            lon=observation.lon,
            time=time,
            wrfout_path=wrfout_path,
        )
        forecast = _forecast_value(summary, variable)
        error = forecast - observed
        nearest = summary["location"]["nearest_grid"]
        pairs.append((observed, forecast))
        matches.append(
            {
                "source_id": observation.source_id,
                "lat": observation.lat,
                "lon": observation.lon,
                "observed": round(observed, 3),
                "forecast": round(forecast, 3),
                "error": round(error, 3),
                "nearest_grid": nearest,
            }
        )

    if not pairs:
        return _empty_score(
            label_key="domain",
            label_value=_domain_label(wrfout_path),
            source=wrfout_path,
            skipped=skipped,
        )

    observed_values = [pair[0] for pair in pairs]
    forecast_values = [pair[1] for pair in pairs]
    errors = [forecast - observed for observed, forecast in pairs]

    return {
        "domain": _domain_label(wrfout_path),
        "source": str(wrfout_path),
        "matched_count": len(pairs),
        "forecast_distribution": _distribution(forecast_values),
        "error_distribution": _distribution(errors),
        "bias": round(mean(errors), 3),
        "mae": round(mean(abs(error) for error in errors), 3),
        "rmse": round(sqrt(mean(error**2 for error in errors)), 3),
        "ks_statistic": round(_ks_statistic(observed_values, forecast_values), 3),
        "matches": matches,
        "skipped_count": len(skipped),
        "skipped_observations": skipped,
    }


def _score_model(
    model_name: str,
    observations: list[Observation],
    forecast_getter,
    variable: str,
    source: Path,
    domain_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    pairs = []
    matches = []
    skipped = []
    for observation in observations:
        observed = _observation_value(observation, variable)
        if observed is None:
            continue

        if domain_bounds is not None and not _point_inside_bounds(observation.lat, observation.lon, domain_bounds):
            skipped.append(_skipped_observation(observation, "outside_domain"))
            continue

        summary = forecast_getter(observation)
        forecast = _forecast_value(summary, variable)
        error = forecast - observed
        pairs.append((observed, forecast))
        matches.append(
            {
                "source_id": observation.source_id,
                "lat": observation.lat,
                "lon": observation.lon,
                "observed": round(observed, 3),
                "forecast": round(forecast, 3),
                "error": round(error, 3),
                "nearest_grid": summary["location"]["nearest_grid"],
            }
        )

    if not pairs:
        return _empty_score(
            label_key="model",
            label_value=model_name,
            source=source,
            skipped=skipped,
        )

    observed_values = [pair[0] for pair in pairs]
    forecast_values = [pair[1] for pair in pairs]
    errors = [forecast - observed for observed, forecast in pairs]

    return {
        "model": model_name,
        "source": str(source),
        "matched_count": len(pairs),
        "forecast_distribution": _distribution(forecast_values),
        "error_distribution": _distribution(errors),
        "bias": round(mean(errors), 3),
        "mae": round(mean(abs(error) for error in errors), 3),
        "rmse": round(sqrt(mean(error**2 for error in errors)), 3),
        "ks_statistic": round(_ks_statistic(observed_values, forecast_values), 3),
        "matches": matches,
        "skipped_count": len(skipped),
        "skipped_observations": skipped,
    }


def _empty_score(
    label_key: str,
    label_value: str,
    source: Path,
    skipped: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        label_key: label_value,
        "source": str(source),
        "matched_count": 0,
        "forecast_distribution": None,
        "error_distribution": None,
        "bias": None,
        "mae": None,
        "rmse": None,
        "ks_statistic": None,
        "matches": [],
        "skipped_count": len(skipped),
        "skipped_observations": skipped,
    }


def _score_sort_key(score: dict[str, Any]) -> tuple[float, float]:
    rmse = score["rmse"] if score["rmse"] is not None else float("inf")
    mae = score["mae"] if score["mae"] is not None else float("inf")
    return (rmse, mae)


def _wrf_domain_bounds(wrfout_path: Path) -> dict[str, float]:
    with xr.open_dataset(wrfout_path) as dataset:
        if "XLAT" not in dataset or "XLONG" not in dataset:
            raise ValueError(f"WRF output {wrfout_path} needs XLAT/XLONG for domain validation.")
        lat = dataset["XLAT"].isel(Time=0) if "Time" in dataset["XLAT"].dims else dataset["XLAT"]
        lon = dataset["XLONG"].isel(Time=0) if "Time" in dataset["XLONG"].dims else dataset["XLONG"]
        return {
            "lat_min": float(lat.min()),
            "lat_max": float(lat.max()),
            "lon_min": float(lon.min()),
            "lon_max": float(lon.max()),
        }


def _point_inside_bounds(lat: float, lon: float, bounds: dict[str, float]) -> bool:
    return (
        bounds["lat_min"] <= lat <= bounds["lat_max"]
        and bounds["lon_min"] <= lon <= bounds["lon_max"]
    )


def _skipped_observation(observation: Observation, reason: str) -> dict[str, Any]:
    return {
        "source_id": observation.source_id,
        "lat": observation.lat,
        "lon": observation.lon,
        "reason": reason,
    }


def _observation_value(observation: Observation, variable: str) -> float | None:
    return getattr(observation, variable)


def _forecast_value(summary: dict[str, Any], variable: str) -> float:
    path = SUPPORTED_VARIABLES[variable]
    value: Any = summary
    for key in path:
        value = value[key]
    return float(value)


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("Cannot calculate a distribution from no values.")

    sorted_values = sorted(values)
    return {
        "min": round(sorted_values[0], 3),
        "p25": round(_quantile(sorted_values, 0.25), 3),
        "median": round(median(sorted_values), 3),
        "mean": round(mean(sorted_values), 3),
        "p75": round(_quantile(sorted_values, 0.75), 3),
        "max": round(sorted_values[-1], 3),
        "std": round(pstdev(sorted_values), 3),
    }


def _quantile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _ks_statistic(observed: list[float], forecast: list[float]) -> float:
    observed_sorted = sorted(observed)
    forecast_sorted = sorted(forecast)
    thresholds = sorted(set(observed_sorted + forecast_sorted))
    max_delta = 0.0
    for threshold in thresholds:
        observed_cdf = _cdf(observed_sorted, threshold)
        forecast_cdf = _cdf(forecast_sorted, threshold)
        max_delta = max(max_delta, abs(observed_cdf - forecast_cdf))
    return max_delta


def _cdf(sorted_values: list[float], threshold: float) -> float:
    count = 0
    for value in sorted_values:
        if value <= threshold:
            count += 1
    return count / len(sorted_values)


def _domain_label(path: Path) -> str:
    for label in ("d01", "d02", "d03"):
        if label in path.name:
            return label
    return path.stem
