"""Configuration for the Portus / Puertos del Estado ETL source."""

from __future__ import annotations

import os
from pathlib import Path

OBSERVATION_ENDPOINT = "https://poem.puertos.es/portus/StationData"
MODEL_POINT_DISCOVERY_ENDPOINT = (
    "https://portus.puertos.es/portussvr/api/puntosMalla/portus/pred/{model_name}?verif=true"
)
LATEST_POSITION_ENDPOINT = "https://portus.puertos.es/portussvr/api/lastData/positions/{model_point_id}"

DEFAULT_TIMEOUT_SECONDS = int(os.getenv("PREDSEA_PORTUS_TIMEOUT", "60"))
DEFAULT_MAX_RETRIES = int(os.getenv("PREDSEA_PORTUS_MAX_RETRIES", "3"))
DEFAULT_BACKOFF_SECONDS = float(os.getenv("PREDSEA_PORTUS_BACKOFF_SECONDS", "2"))
DEFAULT_LOOKBACK_HOURS = int(os.getenv("PREDSEA_PORTUS_LOOKBACK_HOURS", "48"))
DEFAULT_MODEL_NAME = os.getenv("PREDSEA_PORTUS_MODEL_NAME", "Cirana")
DEFAULT_MODEL_POINT_LIMIT = int(os.getenv("PREDSEA_PORTUS_MODEL_POINT_LIMIT", "5"))
DEFAULT_FETCH_LATEST_POSITIONS = os.getenv("PREDSEA_PORTUS_FETCH_LATEST_POSITIONS", "0") == "1"
RAW_CACHE_DIR = Path(os.getenv("PREDSEA_PORTUS_CACHE_DIR", "mvp_data/portus"))


def _split_csv_env(name, default=None):
    raw = os.getenv(name)
    if raw is None:
        return default
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values if values else default


DEFAULT_STATION_CODES = _split_csv_env("PREDSEA_PORTUS_STATION_CODES", ["3545"])
DEFAULT_OBSERVATION_PARAMS = _split_csv_env("PREDSEA_PORTUS_OBSERVATION_PARAMS", None)
