#!/usr/bin/env python3
"""Validate a PredSea marine region profile before any model is launched."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


MODEL_REQUIREMENTS = {
    "swan": {
        "settings": {
            "directions": lambda value: isinstance(value, int) and value >= 12,
            "frequencies": lambda value: isinstance(value, int) and value >= 16,
            "computational_timestep_minutes": lambda value: (
                isinstance(value, int) and value > 0
            ),
        },
    },
    "croco": {
        "settings": {
            "vertical_levels": lambda value: isinstance(value, int) and value >= 10,
        },
    },
}


def validate_region(path: Path) -> dict:
    region = json.loads(path.read_text())
    errors: list[str] = []
    if region.get("schema_version") != "predsea.marine_region.v1":
        errors.append("unsupported schema_version")

    region_id = region.get("region_id")
    if not isinstance(region_id, str) or not region_id:
        errors.append("missing region_id")

    bbox = region.get("bbox") or {}
    required_bbox = (
        "longitude_min",
        "longitude_max",
        "latitude_min",
        "latitude_max",
    )
    for key in required_bbox:
        if not isinstance(bbox.get(key), (int, float)):
            errors.append(f"bbox missing numeric {key}")
    if not errors:
        if not -180 <= bbox["longitude_min"] < bbox["longitude_max"] <= 180:
            errors.append("longitude bounds are invalid or unordered")
        if not -90 <= bbox["latitude_min"] < bbox["latitude_max"] <= 90:
            errors.append("latitude bounds are invalid or unordered")

    resolution = region.get("horizontal_resolution_m")
    if not isinstance(resolution, (int, float)) or resolution <= 0:
        errors.append("horizontal_resolution_m must be positive")
    output_interval = region.get("output_interval_hours")
    if not isinstance(output_interval, int) or output_interval <= 0:
        errors.append("output_interval_hours must be a positive integer")

    # Optional allowlist for profiles that intentionally run a subset of
    # models (e.g. a SWAN-only basin-wide domain that has no CROCO grid at
    # all). Absent entirely, behavior is unchanged from before this field
    # existed: every model in MODEL_REQUIREMENTS is mandatory.
    models_enabled = region.get("models_enabled")
    if models_enabled is None:
        models_enabled = list(MODEL_REQUIREMENTS.keys())
    elif not isinstance(models_enabled, list) or not models_enabled:
        errors.append("models_enabled, if present, must be a non-empty list")
        models_enabled = []
    unknown_models = sorted(set(models_enabled) - set(MODEL_REQUIREMENTS.keys()))
    if unknown_models:
        errors.append(f"models_enabled has unknown model(s): {', '.join(unknown_models)}")

    models = region.get("models") or {}
    for model, requirement in MODEL_REQUIREMENTS.items():
        if model not in models_enabled:
            continue
        model_spec = models.get(model)
        if not isinstance(model_spec, dict):
            errors.append(f"missing model configuration {model}")
            continue
        required_variables = model_spec.get("required_variables") or []
        if not required_variables:
            errors.append(f"{model} has no required_variables")
        if len(required_variables) != len(set(required_variables)):
            errors.append(f"{model} has duplicate required_variables")
        ranges = model_spec.get("physical_ranges") or {}
        for variable in required_variables:
            bounds = ranges.get(variable)
            if (
                not isinstance(bounds, list)
                or len(bounds) != 2
                or not all(isinstance(value, (int, float)) for value in bounds)
                or bounds[0] >= bounds[1]
            ):
                errors.append(f"{model}.{variable} has invalid physical range")
        for setting, predicate in requirement["settings"].items():
            if not predicate(model_spec.get(setting)):
                errors.append(f"{model}.{setting} is invalid")

    if isinstance(output_interval, int) and output_interval > 0:
        timestep = (models.get("swan") or {}).get(
            "computational_timestep_minutes"
        )
        if isinstance(timestep, int) and timestep > 0:
            if output_interval * 60 % timestep:
                errors.append(
                    "SWAN computational timestep must divide the publication interval"
                )

    forcing = region.get("forcing") or {}
    required_forcing_fields = ["atmosphere"]
    if "croco" in models_enabled:
        required_forcing_fields.append("ocean_initial_and_boundary")
    if "swan" in models_enabled:
        required_forcing_fields.append("wave_open_boundary")
    for field in required_forcing_fields:
        if not forcing.get(field):
            errors.append(f"forcing missing {field}")

    return {
        "schema_version": "predsea.marine_region_validation.v1",
        "status": "succeeded" if not errors else "failed",
        "profile": str(path),
        "region_id": region_id,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", type=Path)
    args = parser.parse_args(argv)
    report = validate_region(args.profile)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
