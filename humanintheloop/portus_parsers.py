"""Normalization helpers for Portus observation and model-point payloads."""

from __future__ import annotations

import re

import pandas as pd


VARIABLE_ALIASES = {
    "hm0": "hs_m",
    "hmax": "hmax_m",
    "tm02": "tm02_s",
    "tp": "tp_s",
    "wind_speed": "wind_speed_mps",
    "wind_direction": "wind_direction_deg",
    "wind_dir": "wind_direction_deg",
    "wind_gust": "wind_gust_mps",
    "gust": "wind_gust_mps",
    "current_speed": "current_speed_mps",
    "current_direction": "current_direction_deg",
    "current_dir": "current_direction_deg",
    "temperature": "temperature_c",
    "temp": "temperature_c",
    "air_temperature": "air_temperature_c",
    "water_temperature": "water_temperature_c",
    "sea_temperature": "water_temperature_c",
    "sst": "water_temperature_c",
}


def normalize_variable_name(raw_name):
    name = str(raw_name).strip()
    name = re.sub(r"\s*\(.*?\)", "", name)
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return VARIABLE_ALIASES.get(key, key)


def _coerce_value_qc(cell):
    if isinstance(cell, (list, tuple)) and len(cell) >= 2:
        return cell[0], cell[1]
    return cell, None


def parse_station_data(payload, station_code):
    headers, rows = payload
    variables = headers[1:]

    records = []
    for row in rows:
        ts = row[0]
        record = {
            "source": "puertos_portus",
            "station_code": str(station_code),
            "time_utc": pd.to_datetime(ts, unit="s", utc=True),
        }

        for index, raw_name in enumerate(variables, start=1):
            clean = normalize_variable_name(raw_name)
            value, qc = _coerce_value_qc(row[index])
            if value == -9999.9:
                value = None
            record[clean] = value
            record[f"{clean}_qc"] = qc

        records.append(record)

    return pd.DataFrame(records)


def parse_model_points(payload):
    entries = payload.get("results") if isinstance(payload, dict) and "results" in payload else payload
    records = []
    for item in entries or []:
        record = {
            "source": "puertos_portus",
            "model_point_id": item.get("id"),
            "model_name": item.get("modelo"),
            "lat": item.get("latitud"),
            "lon": item.get("longitud"),
            "region": item.get("region"),
            "station_code_for_verification": item.get("codigoEstacion"),
            "time_step": item.get("tdelta"),
            "time_unit": item.get("tunidad"),
            "type": item.get("tipo"),
        }
        records.append(record)
    return pd.DataFrame(records)


def parse_last_positions(payload, model_point_id, station_code_for_verification=None):
    entries = payload
    if isinstance(payload, dict) and "results" in payload:
        entries = payload["results"]
    elif isinstance(payload, dict) and any(isinstance(value, list) for value in payload.values()):
        entries = [payload]
    elif not isinstance(payload, list):
        entries = [payload]

    records = []
    for item in entries or []:
        if isinstance(item, dict):
            record = dict(item)
        elif isinstance(item, list):
            record = {"values": item}
        else:
            record = {"value": item}
        record["source"] = "puertos_portus"
        record["model_point_id"] = model_point_id
        if station_code_for_verification is not None:
            record["station_code_for_verification"] = station_code_for_verification
        records.append(record)

    return pd.DataFrame(records)

