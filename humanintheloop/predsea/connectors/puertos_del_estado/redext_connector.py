from __future__ import annotations

from .etl import fetch_network_observations
from .redext_parser import parse_station_dataset


def fetch_redext_observations(**kwargs):
    return fetch_network_observations("redext", parser_fn=parse_station_dataset, **kwargs)
