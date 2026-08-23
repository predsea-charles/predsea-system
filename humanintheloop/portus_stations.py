"""Declarative Portus station and model-point configuration."""

from __future__ import annotations

import os


DEFAULT_OBSERVATION_STATIONS = [
    {
        "code": "3545",
        "key": "portus_3545",
        "label": "Portus station 3545",
    }
]


def load_observation_stations():
    raw = os.getenv("PREDSEA_PORTUS_STATION_CODES")
    if not raw:
        return list(DEFAULT_OBSERVATION_STATIONS)

    stations = []
    for code in [item.strip() for item in raw.split(",") if item.strip()]:
        stations.append(
            {
                "code": code,
                "key": f"portus_{code}",
                "label": f"Portus station {code}",
            }
        )
    return stations

