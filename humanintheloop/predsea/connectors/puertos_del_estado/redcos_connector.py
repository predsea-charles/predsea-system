from __future__ import annotations

from .etl import fetch_network_observations
from .redcos_parser import parse_station_dataset


def fetch_redcos_observations(**kwargs):
    return fetch_network_observations("redcos", parser_fn=parse_station_dataset, **kwargs)
