from __future__ import annotations

from .hfradar_connector import parse_station_dataset as parse_hfradar_station_dataset
from .redcos_parser import parse_station_dataset as parse_redcos_station_dataset
from .redext_parser import parse_station_dataset as parse_redext_station_dataset
from .redmar_parser import parse_station_dataset as parse_redmar_station_dataset


def parse_station_dataset(ds, station_meta, dataset_url=None):
    network = (station_meta or {}).get("network")
    if network == "redmar":
        return parse_redmar_station_dataset(ds, station_meta, dataset_url=dataset_url)
    if network == "redcos":
        return parse_redcos_station_dataset(ds, station_meta, dataset_url=dataset_url)
    if network == "hfradar":
        return parse_hfradar_station_dataset(ds, station_meta, dataset_url=dataset_url)
    return parse_redext_station_dataset(ds, station_meta, dataset_url=dataset_url)
