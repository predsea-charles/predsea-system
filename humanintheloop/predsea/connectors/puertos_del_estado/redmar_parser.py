from __future__ import annotations

from .common import SOURCE_SYSTEM, normalize_text
from .normalize_observations import build_measurement_record, sampled_valid_samples_from_dataarray


def _qc_dataarray_for_measurement(ds, source_field):
    qc_candidates = (
        f"{source_field}_QC",
        f"{source_field}_qc",
        f"{source_field}_DM",
        f"{source_field}_dm",
    )
    for candidate in qc_candidates:
        if candidate in ds.data_vars:
            return ds[candidate]
    return None


def _variable_from_attrs(source_field, da):
    text = " ".join(
        part
        for part in (
            normalize_text(source_field),
            normalize_text(da.attrs.get("long_name")),
            normalize_text(da.attrs.get("standard_name")),
            normalize_text(da.name),
        )
        if part
    )
    if any(token in text for token in ("sea_level_residual", "residual")):
        return "sea_level_residual", "sea_level_residual_m"
    if any(token in text for token in ("slev", "sea_level", "observed_sea_level", "sea_surface_height")):
        return "sea_level", "sea_level_m"
    if any(token in text for token in ("deph", "depth")):
        return "depth", "depth_m"
    if "pressure" in text:
        return "air_pressure", "air_pressure_hpa"
    if "temperature" in text and "water" in text:
        return "water_temperature", "water_temperature_c"
    if "temperature" in text:
        return "air_temperature", "air_temperature_c"
    if "wind_direction" in text:
        return "wind_direction", "wind_direction_deg"
    if "wind_speed" in text:
        return "wind_speed", "wind_speed_mps"
    return None, None


def parse_station_dataset(ds, station_meta, dataset_url=None):
    records = []
    latitude = station_meta.get("latitude")
    longitude = station_meta.get("longitude")
    for source_field, da in ds.data_vars.items():
        source_key = normalize_text(source_field)
        if source_key.endswith("_qc") or source_key.endswith("_dm") or source_key in {"time_qc", "position_qc"}:
            continue
        variable, raw_key = _variable_from_attrs(source_field, da)
        if not variable or not raw_key:
            continue
        qc_da = _qc_dataarray_for_measurement(ds, source_field)
        samples = sampled_valid_samples_from_dataarray(da, latitude=latitude, longitude=longitude, qc_da=qc_da)
        if not samples:
            continue
        for sample in samples:
            records.append(
                build_measurement_record(
                    station_meta,
                    raw_key=raw_key,
                    variable=variable,
                    source_field=source_field,
                    value=sample["value"],
                    units=da.attrs.get("units"),
                    sample=sample,
                    qc_flag=sample.get("qc_flag"),
                    is_qc_good=sample.get("is_qc_good"),
                    source_label="REDMAR",
                    source_system=SOURCE_SYSTEM,
                    dataset_url=dataset_url,
                    latitude=latitude,
                    longitude=longitude,
                )
            )
    return records
