from __future__ import annotations

import warnings
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


warnings.filterwarnings(
    "ignore",
    message="Discarding nonzero nanoseconds in conversion",
    category=UserWarning,
)


SOURCE_SYSTEM = "puertos_del_estado"
NETWORK_LABELS = {
    "redext": "REDEXT",
    "redcos": "REDCOS",
    "redmar": "REDMAR",
    "hfradar": "HF_RADAR",
}


def strip_accents(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text):
    text = strip_accents(str(text or "")).strip().lower()
    text = re.sub(r"\s*\(.*?\)", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def clean_station_name(label):
    text = strip_accents(str(label or "")).strip()
    text = re.sub(r"^Boya Costera de\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Boya de\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Boya\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Estacion\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(.*?\)", "", text)
    return text.strip()


def station_key_from_label(label):
    return normalize_text(clean_station_name(label))


def station_id_from_label(label):
    key = station_key_from_label(label)
    return f"puertos_{key}" if key else None


def parse_utc_timestamp(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        parsed = pd.to_datetime(value, utc=True)
    except Exception:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.to_pydatetime().astimezone(timezone.utc)
    return parsed


def timestamp_text(value):
    parsed = parse_utc_timestamp(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_future_timestamp(candidate, reference=None, *, tolerance_minutes=5):
    candidate_dt = parse_utc_timestamp(candidate)
    reference_dt = parse_utc_timestamp(reference) if reference is not None else datetime.now(timezone.utc)
    if candidate_dt is None or reference_dt is None:
        return False
    return candidate_dt > reference_dt + timedelta(minutes=tolerance_minutes)


def to_float(value):
    try:
        if value is None:
            return None
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        if isinstance(value, np.ndarray) and value.size:
            value = value.reshape(-1)[0]
        return float(value)
    except Exception:
        return None


def _time_dim_name(da):
    for dim in da.dims:
        if dim.lower() in {"time", "time_counter", "datetime"}:
            return dim
    return None


def _spatial_dims(da):
    dims = [dim for dim in da.dims if dim.lower() != "time" and da.sizes.get(dim, 0) > 1]
    return dims


def _coordinate_values(coord):
    try:
        values = np.asarray(coord.values)
    except Exception:
        values = np.asarray(coord)
    return values


def select_spatial_point(da, latitude, longitude):
    def _coord(*names):
        for name in names:
            coord = da.coords.get(name)
            if coord is not None:
                return coord
        return None

    lat_coord = _coord("latitude", "LATITUDE", "lat", "LAT")
    lon_coord = _coord("longitude", "LONGITUDE", "lon", "LON")
    if lat_coord is None or lon_coord is None:
        return da

    lat_values = _coordinate_values(lat_coord)
    lon_values = _coordinate_values(lon_coord)

    if lat_values.ndim == 1 and lon_values.ndim == 1:
        try:
            return da.sel(latitude=latitude, longitude=longitude, method="nearest")
        except Exception:
            return da

    if lat_values.shape == lon_values.shape and lat_values.ndim >= 2:
        distance = ((lat_values - float(latitude)) ** 2) + ((lon_values - float(longitude)) ** 2)
        flat_index = int(np.nanargmin(distance))
        unravelled = np.unravel_index(flat_index, distance.shape)
        spatial_dims = _spatial_dims(da)
        if len(spatial_dims) >= len(unravelled):
            selections = {dim: idx for dim, idx in zip(spatial_dims[: len(unravelled)], unravelled)}
            try:
                return da.isel(selections)
            except Exception:
                return da

    return da


def latest_value_from_dataarray(
    da,
    *,
    latitude=None,
    longitude=None,
    qc_da=None,
    fill_values=None,
    now_utc=None,
):
    sample = latest_sample_from_dataarray(
        da,
        latitude=latitude,
        longitude=longitude,
        qc_da=qc_da,
        fill_values=fill_values,
        now_utc=now_utc,
    )
    if sample is None:
        return None, None
    return sample["value"], sample["source_time_coordinate_utc"]


def latest_sample_from_dataarray(
    da,
    *,
    latitude=None,
    longitude=None,
    qc_da=None,
    fill_values=None,
    now_utc=None,
    tolerance_minutes=5,
):
    from .normalize_observations import latest_valid_sample_from_dataarray

    return latest_valid_sample_from_dataarray(
        da,
        qc_da=qc_da,
        fill_values=fill_values,
        latitude=latitude,
        longitude=longitude,
        now_utc=now_utc,
        tolerance_minutes=tolerance_minutes,
    )


def variable_keyword(text):
    return normalize_text(" ".join(part for part in [text] if part))
