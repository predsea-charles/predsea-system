"""Fail-closed discovery and validation for model NetCDF outputs.

WPS ``met_em`` files share a directory and a NetCDF suffix with model output,
but they are inputs to WRF, not forecasts.  Never infer a model from the suffix
alone: both the object name and the dataset's variables must match the model.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence

import xarray as xr


_WRF_NAME = re.compile(r"^(?:wrfout_d0[1-9]_.+|wrf_d0[1-9]\.nc4?)$", re.IGNORECASE)


def is_model_output_name(name: str, model: str) -> bool:
    """Return whether a GCS object name is an explicit output for ``model``."""
    lower_name = name.lower()
    basename = Path(lower_name).name
    if basename.startswith(("met_em.", "geo_em.", "wrfinput_", "wrfbdy_")):
        return False
    if not basename.endswith((".nc", ".nc4")) and model != "wrf":
        return False

    if model == "wrf":
        return bool(_WRF_NAME.match(basename))
    if model == "croco":
        return (
            any(token in basename for token in ("croco", "roms", "his", "avg"))
            and ("/roms/" in f"/{lower_name}" or "croco" in basename or "roms" in basename)
        )
    if model == "nemo":
        return any(token in basename for token in ("nemo", "orca"))
    if model == "swan":
        return "swan" in basename or basename.startswith("wave_")
    raise ValueError(f"Unsupported model: {model}")


def candidate_blobs(blobs: Iterable[object], model: str) -> list[object]:
    """Select deterministic, explicitly named candidates; never generic NetCDF."""
    return sorted(
        (blob for blob in blobs if is_model_output_name(blob.name, model)),
        key=lambda blob: blob.name,
    )


def _has_any(names: set[str], alternatives: Sequence[str]) -> bool:
    return any(name in names for name in alternatives)


def validate_model_output(path: str | Path, model: str) -> tuple[bool, str]:
    """Validate the cheap content signature that distinguishes each model output."""
    try:
        with xr.open_dataset(path, decode_times=False) as dataset:
            names = set(dataset.variables)
    except Exception as exc:
        return False, f"cannot open NetCDF: {exc}"

    if model == "wrf":
        valid = {"XLAT", "XLONG"}.issubset(names)
        expected = "XLAT and XLONG"
    elif model == "croco":
        valid = (
            _has_any(names, ("lat_rho", "latitude", "lat"))
            and _has_any(names, ("lon_rho", "longitude", "lon"))
            and _has_any(names, ("u", "uo", "u_current", "eastward_sea_water_velocity"))
            and _has_any(names, ("v", "vo", "v_current", "northward_sea_water_velocity"))
        )
        expected = "CROCO coordinates and current components"
    elif model == "nemo":
        valid = (
            _has_any(names, ("nav_lat", "latitude", "lat"))
            and _has_any(names, ("nav_lon", "longitude", "lon"))
            and _has_any(names, ("uo", "u", "eastward_sea_water_velocity"))
            and _has_any(names, ("vo", "v", "northward_sea_water_velocity"))
        )
        expected = "NEMO coordinates and current components"
    elif model == "swan":
        valid = (
            _has_any(names, ("latitude", "lat", "XLAT", "nav_lat", "lat_rho"))
            and _has_any(names, ("longitude", "lon", "XLONG", "nav_lon", "lon_rho"))
            and _has_any(names, ("hs", "hsign", "significant_wave_height", "swh", "hsig", "Hsign"))
        )
        expected = "SWAN coordinates and significant wave height"
    else:
        raise ValueError(f"Unsupported model: {model}")

    return (True, "ok") if valid else (False, f"missing {expected}")


def download_first_valid(candidates: Iterable[object], model: str, local_path: str | Path) -> object | None:
    """Download candidates in order and return the first content-valid blob."""
    for blob in candidates:
        blob.download_to_filename(str(local_path))
        valid, reason = validate_model_output(local_path, model)
        if valid:
            return blob
        print(f"⚠️ Rejecting gs://.../{blob.name} as {model.upper()} output: {reason}")
    return None
