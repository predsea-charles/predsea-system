from __future__ import annotations

from .etl import fetch_network_observations
from .redmar_parser import parse_station_dataset


def fetch_redmar_observations(**kwargs):
    return fetch_network_observations("redmar", parser_fn=parse_station_dataset, **kwargs)
