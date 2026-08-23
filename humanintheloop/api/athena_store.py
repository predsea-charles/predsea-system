"""Athena queries used by the AWS API runtime."""
from __future__ import annotations

import os
import re

from scripts.aws.cloud import query_athena


def _literal(value: str, pattern: str) -> str:
    if not re.fullmatch(pattern, value or ""):
        raise ValueError(f"Unsafe Athena filter value: {value!r}")
    return "'" + value.replace("'", "''") + "'"


def prioritized_forecasts(run_date: str, place_id: str) -> list[dict]:
    date_value = _literal(run_date, r"\d{4}-\d{2}-\d{2}")
    place_value = _literal(place_id, r"[A-Za-z0-9_.:-]{1,128}")
    database = os.getenv("PREDSEA_ATHENA_DATABASE", "predsea_validation")
    table = os.getenv("PREDSEA_ATHENA_EVIDENCE_TABLE", "evidence_rows")
    rows = query_athena(f"""
        WITH raw_forecasts AS (
          SELECT variable, target_time_utc, value, lead_time_hours, provider,
            CASE WHEN lead_time_hours <= 120 THEN
              CASE WHEN provider IN ('predsea_wrf','predsea_croco','predsea_ww3') THEN 1
                   WHEN provider IN ('arome_1km','cmems_nemo','cmems_ww3') THEN 2 ELSE 3 END
            ELSE CASE WHEN provider IN ('copernicus','cmems_nemo','cmems_ww3') THEN 1 ELSE 2 END END AS priority_rank,
            ingested_at_utc
          FROM {database}.{table}
          WHERE record_type='forecast' AND run_date={date_value}
            AND reference_station_id={place_value} AND lead_time_hours BETWEEN 0 AND 240
        ), ranked AS (
          SELECT *, row_number() OVER (
            PARTITION BY target_time_utc, variable ORDER BY priority_rank, ingested_at_utc DESC
          ) AS rnk FROM raw_forecasts
        )
        SELECT variable, target_time_utc, value, provider, priority_rank FROM ranked WHERE rnk=1
    """)
    for row in rows:
        if row.get("value") is not None:
            row["value"] = float(row["value"])
        if row.get("priority_rank") is not None:
            row["priority_rank"] = int(row["priority_rank"])
    return rows


def latest_observation_stations(variable: str | None, lookback_days: int) -> list[dict]:
    if not 1 <= lookback_days <= 30:
        raise ValueError("lookback_days must be between 1 and 30")
    variable_filter = ""
    if variable:
        variable_filter = f"AND variable={_literal(variable, r'[A-Za-z0-9_.:-]{1,128}')}"
    database = os.getenv("PREDSEA_ATHENA_DATABASE", "predsea_validation")
    table = os.getenv("PREDSEA_ATHENA_EVIDENCE_TABLE", "evidence_rows")
    rows = query_athena(f"""
      WITH station AS (
        SELECT station_id, station_name, station_kind, network, provider, latitude, longitude,
          row_number() OVER (PARTITION BY station_id ORDER BY ingested_at_utc DESC) rnk
        FROM {database}.{table} WHERE record_type='station_metadata'
      ), observation AS (
        SELECT station_id, variable, value, units, observed_at_utc,
          row_number() OVER (PARTITION BY station_id, variable ORDER BY observed_at_utc DESC) rnk
        FROM {database}.{table}
        WHERE record_type='observation'
          AND observed_at_utc >= current_timestamp - INTERVAL '{lookback_days}' DAY
          AND value IS NOT NULL {variable_filter}
      )
      SELECT s.station_id, s.station_name, s.station_kind, s.network, s.provider,
        s.latitude, s.longitude, o.variable, o.value, o.units, o.observed_at_utc
      FROM station s LEFT JOIN observation o ON o.station_id=s.station_id AND o.rnk=1
      WHERE s.rnk=1
    """)
    for row in rows:
        for field in ("value", "latitude", "longitude"):
            if row.get(field) is not None:
                row[field] = float(row[field])
    return rows
