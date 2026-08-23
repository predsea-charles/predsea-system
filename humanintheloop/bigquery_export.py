"""BigQuery export helpers for normalized PredSea evidence rows.

The repository already produces two normalized JSONL streams per run:

* ``validation/observation_samples.jsonl``
* ``validation/forecast_index.jsonl``

This module turns those rows into a single BigQuery fact table so the
ETL can backfill historical runs and then append new runs automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import math
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

import validation_archive


DEFAULT_DATASET = "predsea_validation"
DEFAULT_TABLE = "evidence_rows"
DEFAULT_LOCATION = "europe-west1"
DEFAULT_HTTP_TIMEOUT_SECONDS = float(os.environ.get("PREDSEA_BIGQUERY_HTTP_TIMEOUT_SECONDS", "30"))
BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
SCHEMA_VERSION = "predsea.bigquery.evidence_rows.v1"
INSERT_BATCH_SIZE = 500
FAILED_ROW_SAMPLE_LIMIT = 10


@dataclass(frozen=True)
class BigQueryConfig:
    project_id: str
    dataset_id: str
    table_id: str
    location: str = DEFAULT_LOCATION


def sanitize_float(value):
    """Replace JSON-non-compliant floats (NaN, Inf) with None."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _forecast_source_family(row):
    source_id = str(
        row.get("forecast_source_id")
        or row.get("ocean_source")
        or row.get("source_system")
        or ""
    ).lower()
    if source_id in {"meteo_france_arome", "aemet_harmonie_arome", "ecmwf_open_data"}:
        return "atmosphere"
    if source_id:
        return "ocean_forecast"
    return "forecast"


def resolve_config(
    project_id: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
    location: str | None = None,
) -> BigQueryConfig | None:
    if not dataset_id:
        try:
            from api.config import PREDSEA_BIGQUERY_DATASET
            dataset_id = PREDSEA_BIGQUERY_DATASET
        except ImportError:
            env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
            if env not in ("test", "prod"):
                env = "test"
            dataset_id = os.environ.get("PREDSEA_BIGQUERY_DATASET") or f"{DEFAULT_DATASET}_{env}"
    table_id = table_id or os.environ.get("PREDSEA_BIGQUERY_TABLE") or DEFAULT_TABLE
    
    if not project_id:
        project_id = (
            os.environ.get("PREDSEA_BIGQUERY_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
        )
        if not project_id:
            try:
                # Fallback to default project from credentials
                _, auth_project = google_auth_default_project()
                project_id = auth_project
            except Exception:
                pass

    if not project_id or not dataset_id or not table_id:
        return None
    return BigQueryConfig(
        project_id=project_id,
        dataset_id=dataset_id,
        table_id=table_id,
        location=location or os.environ.get("PREDSEA_BIGQUERY_LOCATION") or DEFAULT_LOCATION,
    )


def export_validation_archive_to_bigquery(
    run_dir,
    project_id: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
    location: str | None = None,
    client=None,
    dry_run: bool = False,
):
    """Export normalized validation rows from a run directory to BigQuery.

    The function is intentionally best-effort. If BigQuery is not configured,
    it returns a skipped status instead of failing the ETL.
    """
    validation_dir = Path(run_dir) / "validation"
    if not validation_dir.exists():
        validation_dir = Path(run_dir)

    observation_rows = validation_archive.read_jsonl(validation_dir / "observation_samples.jsonl")
    forecast_rows = validation_archive.read_jsonl(validation_dir / "forecast_index.jsonl")
    source_inventory_rows = validation_archive.read_jsonl(validation_dir / "source_inventory.jsonl")
    rows = build_normalized_rows(observation_rows, forecast_rows, source_inventory_rows)
    config = resolve_config(project_id=project_id, dataset_id=dataset_id, table_id=table_id, location=location)

    if not rows:
        return {
            "status": "skipped",
            "reason": "no normalized validation rows were found",
            "observation_rows": len(observation_rows),
            "forecast_rows": len(forecast_rows),
            "exported_rows": 0,
        }

    if config is None:
        return {
            "status": "skipped",
            "reason": "bigquery configuration is incomplete",
            "observation_rows": len(observation_rows),
            "forecast_rows": len(forecast_rows),
            "exported_rows": 0,
        }

    try:
        if dry_run:
            return {
                "status": "dry_run",
                "project_id": config.project_id,
                "dataset_id": config.dataset_id,
                "table_id": config.table_id,
                "observation_rows": len(observation_rows),
                "forecast_rows": len(forecast_rows),
                "exported_rows": len(rows),
            }

        session = client or authorized_bigquery_session()
        ensure_dataset(session, config)
        ensure_table(session, config)
        insert_result = insert_rows(session, config, rows)
        return {
            "status": insert_result["status"],
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "observation_rows": len(observation_rows),
            "forecast_rows": len(forecast_rows),
            "exported_rows": len(rows),
            "failed_rows": insert_result.get("failed_rows", 0),
            "insert_errors": insert_result.get("insert_errors", []),
            "failed_row_samples": insert_result.get("failed_row_samples", []),
            "error_messages": insert_result.get("error_messages", []),
            "response_status": insert_result.get("response_status"),
            "response_body": insert_result.get("response_body"),
        }
    except Exception as error:
        return {
            "status": "error",
            "reason": str(error),
            "traceback": traceback.format_exc(),
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "observation_rows": len(observation_rows),
            "forecast_rows": len(forecast_rows),
            "exported_rows": len(rows),
        }


def export_station_metadata_to_bigquery(
    run_dir,
    project_id: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
    location: str | None = None,
    client=None,
    dry_run: bool = False,
):
    validation_dir = Path(run_dir) / "validation"
    if not validation_dir.exists():
        validation_dir = Path(run_dir)

    metadata_rows = validation_archive.read_jsonl(validation_dir / "station_metadata.jsonl")
    rows = build_station_metadata_rows(metadata_rows)
    config = resolve_config(
        project_id=project_id,
        dataset_id=dataset_id,
        table_id=table_id or os.environ.get("PREDSEA_BIGQUERY_STATION_METADATA_TABLE") or "station_metadata",
        location=location,
    )

    if not rows:
        return {
            "status": "skipped",
            "reason": "no station metadata rows were found",
            "station_metadata_rows": len(metadata_rows),
            "exported_rows": 0,
        }

    if config is None:
        return {
            "status": "skipped",
            "reason": "bigquery configuration is incomplete",
            "station_metadata_rows": len(metadata_rows),
            "exported_rows": 0,
        }

    try:
        if dry_run:
            return {
                "status": "dry_run",
                "project_id": config.project_id,
                "dataset_id": config.dataset_id,
                "table_id": config.table_id,
                "station_metadata_rows": len(metadata_rows),
                "exported_rows": len(rows),
            }

        session = client or authorized_bigquery_session()
        ensure_dataset(session, config)
        ensure_station_metadata_table(session, config)
        insert_result = insert_rows(session, config, rows)
        return {
            "status": insert_result["status"],
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "station_metadata_rows": len(metadata_rows),
            "exported_rows": len(rows),
            "failed_rows": insert_result.get("failed_rows", 0),
            "insert_errors": insert_result.get("insert_errors", []),
            "failed_row_samples": insert_result.get("failed_row_samples", []),
            "error_messages": insert_result.get("error_messages", []),
            "response_status": insert_result.get("response_status"),
            "response_body": insert_result.get("response_body"),
        }
    except Exception as error:
        return {
            "status": "error",
            "reason": str(error),
            "traceback": traceback.format_exc(),
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "station_metadata_rows": len(metadata_rows),
            "exported_rows": len(rows),
        }


def export_station_metadata_to_bigquery_from_rows(
    metadata_rows: list[dict],
    project_id: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
    location: str | None = None,
    client=None,
    dry_run: bool = False,
):
    """Export station metadata rows that are already in memory to BigQuery."""
    rows = build_station_metadata_rows(metadata_rows)
    config = resolve_config(
        project_id=project_id,
        dataset_id=dataset_id,
        table_id=table_id or os.environ.get("PREDSEA_BIGQUERY_STATION_METADATA_TABLE") or "station_metadata",
        location=location,
    )

    if not rows:
        return {
            "status": "skipped",
            "reason": "no station metadata rows were provided",
            "station_metadata_rows": len(metadata_rows),
            "exported_rows": 0,
        }

    if config is None:
        return {
            "status": "skipped",
            "reason": "bigquery configuration is incomplete",
            "station_metadata_rows": len(metadata_rows),
            "exported_rows": 0,
        }

    try:
        if dry_run:
            return {
                "status": "dry_run",
                "project_id": config.project_id,
                "dataset_id": config.dataset_id,
                "table_id": config.table_id,
                "station_metadata_rows": len(metadata_rows),
                "exported_rows": len(rows),
            }

        session = client or authorized_bigquery_session()
        ensure_dataset(session, config)
        ensure_station_metadata_table(session, config)
        insert_result = insert_rows(session, config, rows)
        return {
            "status": insert_result["status"],
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "station_metadata_rows": len(metadata_rows),
            "exported_rows": len(rows),
            "failed_rows": insert_result.get("failed_rows", 0),
            "insert_errors": insert_result.get("insert_errors", []),
            "failed_row_samples": insert_result.get("failed_row_samples", []),
            "error_messages": insert_result.get("error_messages", []),
            "response_status": insert_result.get("response_status"),
            "response_body": insert_result.get("response_body"),
        }
    except Exception as error:
        return {
            "status": "error",
            "reason": str(error),
            "traceback": traceback.format_exc(),
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "station_metadata_rows": len(metadata_rows),
            "exported_rows": len(rows),
        }


def export_validation_rows_to_bigquery(
    observation_rows,
    forecast_rows,
    source_inventory_rows=None,
    project_id: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
    location: str | None = None,
    client=None,
    dry_run: bool = False,
    run_date: str | None = None,
    run_id: str | None = None,
):
    """Export normalized validation rows that are already in memory.

    The optional run metadata is accepted for symmetry with the archive-based
    helper and for future provenance tracking, but the normalized rows already
    carry the values that BigQuery needs.
    """
    rows = build_normalized_rows(observation_rows, forecast_rows, source_inventory_rows)
    config = resolve_config(project_id=project_id, dataset_id=dataset_id, table_id=table_id, location=location)

    if not rows:
        return {
            "status": "skipped",
            "reason": "no normalized validation rows were found",
            "observation_rows": len(observation_rows or []),
            "forecast_rows": len(forecast_rows or []),
            "exported_rows": 0,
        }

    if config is None:
        return {
            "status": "skipped",
            "reason": "bigquery configuration is incomplete",
            "observation_rows": len(observation_rows or []),
            "forecast_rows": len(forecast_rows or []),
            "exported_rows": 0,
        }

    try:
        if dry_run:
            return {
                "status": "dry_run",
                "project_id": config.project_id,
                "dataset_id": config.dataset_id,
                "table_id": config.table_id,
                "observation_rows": len(observation_rows or []),
                "forecast_rows": len(forecast_rows or []),
                "exported_rows": len(rows),
            }

        session = client or authorized_bigquery_session()
        ensure_dataset(session, config)
        ensure_table(session, config)
        insert_result = insert_rows(session, config, rows)
        return {
            "status": insert_result["status"],
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "observation_rows": len(observation_rows or []),
            "forecast_rows": len(forecast_rows or []),
            "exported_rows": len(rows),
            "failed_rows": insert_result.get("failed_rows", 0),
            "insert_errors": insert_result.get("insert_errors", []),
            "failed_row_samples": insert_result.get("failed_row_samples", []),
            "error_messages": insert_result.get("error_messages", []),
            "response_status": insert_result.get("response_status"),
            "response_body": insert_result.get("response_body"),
        }
    except Exception as error:
        return {
            "status": "error",
            "reason": str(error),
            "traceback": traceback.format_exc(),
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "observation_rows": len(observation_rows or []),
            "forecast_rows": len(forecast_rows or []),
            "exported_rows": len(rows),
        }


def build_normalized_rows(observation_rows, forecast_rows, source_inventory_rows=None):
    ingested_at_utc = current_timestamp_utc()
    rows = []
    for row in observation_rows or []:
        rows.append(normalize_observation_row(row, ingested_at_utc=ingested_at_utc))
    for row in forecast_rows or []:
        rows.append(normalize_forecast_row(row, ingested_at_utc=ingested_at_utc))
    for row in source_inventory_rows or []:
        rows.append(normalize_source_inventory_row(row, ingested_at_utc=ingested_at_utc))
    return sorted(
        rows,
        key=lambda row: (
            row.get("run_id") or "",
            row.get("record_type") or "",
            row.get("reference_station_id") or row.get("station_id") or "",
            row.get("variable") or "",
            row.get("sample_time_utc") or "",
        ),
    )


def build_station_metadata_rows(metadata_rows):
    rows = []
    ingested_at_utc = current_timestamp_utc()
    for row in metadata_rows or []:
        normalized = normalize_station_metadata_row(row, ingested_at_utc=ingested_at_utc)
        if normalized is not None:
            rows.append(normalized)
    return sorted(
        rows,
        key=lambda row: (
            row.get("provider") or "",
            row.get("network") or "",
            row.get("station_name") or "",
            row.get("station_id") or "",
        ),
    )


def normalize_observation_row(row, ingested_at_utc):
    sample_time_utc = bigquery_timestamp(row.get("sample_time_utc") or row.get("observed_at_utc"))
    observed_at_utc = bigquery_timestamp(row.get("observed_at_utc") or row.get("sample_time_utc"))
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "observation",
        "source_family": row.get("source_family") or "observation",
        "run_date": row.get("run_date"),
        "run_id": row.get("run_id"),
        "ingested_at_utc": ingested_at_utc,
        "source_system": row.get("source_system") or row.get("provider"),
        "source_label": row.get("source_label") or row.get("station_name"),
        "route_id": None,
        "route_name": None,
        "station_id": row.get("station_id"),
        "station_name": row.get("station_name"),
        "reference_station_id": row.get("station_id"),
        "reference_station_name": row.get("station_name"),
        "variable": row.get("variable"),
        "value": numeric_value(row.get("value")),
        "units": row.get("units"),
        "sample_time_utc": sample_time_utc,
        "observed_at_utc": observed_at_utc,
        "source_time_coordinate_utc": bigquery_timestamp(row.get("source_time_coordinate_utc") or row.get("sample_time_utc") or row.get("observed_at_utc")),
        "forecast_created_at_utc": None,
        "target_time_utc": None,
        "target_local_time": None,
        "lead_time_hours": None,
        "resolution_km": None,
        "forecast_source_id": None,
        "forecast_source_label": None,
        "ocean_source": None,
        "truth_station_id": None,
        "truth_station_name": None,
        "source_field": row.get("source_field"),
        "dataset_url": row.get("dataset_url"),
        "provider": row.get("provider"),
        "network": row.get("network"),
        "station_kind": row.get("station_kind"),
        "priority": row.get("priority"),
        "latitude": numeric_value(row.get("latitude")),
        "longitude": numeric_value(row.get("longitude")),
        "depth_m": numeric_value(row.get("depth_m")),
        "qc_flag": row.get("qc_flag"),
        "freshness_status": row.get("freshness_status") or row.get("freshness_state"),
        "freshness_state": row.get("freshness_state") or (row.get("freshness_status") or "").upper(),
        "quality_score": numeric_value(row.get("quality_score")),
        "is_future": row.get("is_future"),
        "is_future_timestamp": row.get("is_future_timestamp") or row.get("is_future"),
        "is_qc_good": row.get("is_qc_good"),
        "variables_supported": row.get("variables_supported") or [],
        "nearest_routes": row.get("nearest_routes") or [],
        "distance_to_route_nm": numeric_value(row.get("distance_to_route_nm")),
        "distance_to_palma": numeric_value(row.get("distance_to_palma")),
        "distance_to_ibiza": numeric_value(row.get("distance_to_ibiza")),
        "distance_to_menorca": numeric_value(row.get("distance_to_menorca")),
    }
    allowed_fields = {field["name"] for field in bigquery_schema()}
    filtered_normalized = {
        key: sanitize_float(value)
        for key, value in normalized.items()
        if key in allowed_fields
    }
    filtered_normalized["row_hash"] = stable_row_hash(filtered_normalized)
    return filtered_normalized


def normalize_forecast_row(row, ingested_at_utc):
    target_time_utc = bigquery_timestamp(row.get("target_time_utc"))
    forecast_created_at_utc = bigquery_timestamp(row.get("forecast_created_at_utc"))
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "forecast",
        "source_family": row.get("source_family") or _forecast_source_family(row),
        "run_date": row.get("run_date"),
        "run_id": row.get("run_id"),
        "ingested_at_utc": ingested_at_utc,
        "source_system": row.get("forecast_source_id") or row.get("ocean_source"),
        "source_label": row.get("forecast_source_label"),
        "route_id": row.get("route_id"),
        "route_name": row.get("route_name"),
        "station_id": None,
        "station_name": None,
        "reference_station_id": row.get("truth_station_id"),
        "reference_station_name": row.get("truth_station_name"),
        "variable": row.get("variable"),
        "value": numeric_value(row.get("value")),
        "units": row.get("units"),
        "sample_time_utc": target_time_utc,
        "observed_at_utc": None,
        "forecast_created_at_utc": forecast_created_at_utc,
        "target_time_utc": target_time_utc,
        "target_local_time": row.get("target_local_time"),
        "lead_time_hours": numeric_value(row.get("lead_time_hours")),
        "resolution_km": numeric_value(row.get("resolution_km")),
        "forecast_source_id": row.get("forecast_source_id"),
        "forecast_source_label": row.get("forecast_source_label"),
        "ocean_source": row.get("ocean_source"),
        "truth_station_id": row.get("truth_station_id"),
        "truth_station_name": row.get("truth_station_name"),
        "source_field": row.get("source_field"),
        "provider": row.get("provider") or row.get("forecast_source_id") or row.get("ocean_source"),
        "network": row.get("network") or row.get("forecast_source_id") or row.get("ocean_source"),
        "latitude": numeric_value(row.get("latitude")),
        "longitude": numeric_value(row.get("longitude")),
    }
    normalized["source_field"] = row.get("source_field")

    # Dynamic filtering layer against local schema definition
    allowed_fields = {field["name"] for field in bigquery_schema()}
    filtered_normalized = {
        key: sanitize_float(value)
        for key, value in normalized.items()
        if key in allowed_fields
    }

    filtered_normalized["row_hash"] = stable_row_hash(filtered_normalized)
    return filtered_normalized


def normalize_station_metadata_row(row, ingested_at_utc):
    variables_supported = row.get("variables_supported") or []
    if not isinstance(variables_supported, list):
        variables_supported = [variables_supported]
    normalized = {
        "schema_version": row.get("schema_version") or SCHEMA_VERSION,
        "row_hash": None,
        "record_type": "station_metadata",
        "source_family": row.get("source_family") or "observation",
        "run_date": row.get("run_date"),
        "run_id": row.get("run_id"),
        "ingested_at_utc": ingested_at_utc,
        "source_system": row.get("provider") or row.get("network"),
        "source_label": row.get("source_label"),
        "route_id": None,
        "route_name": None,
        "station_id": row.get("station_id"),
        "station_name": row.get("station_name"),
        "reference_station_id": None,
        "reference_station_name": None,
        "variable": "station_metadata",
        "value": None,
        "units": None,
        "sample_time_utc": bigquery_timestamp(row.get("last_sample_utc")),
        "observed_at_utc": bigquery_timestamp(row.get("last_sample_utc")),
        "forecast_created_at_utc": None,
        "target_time_utc": None,
        "target_local_time": None,
        "lead_time_hours": None,
        "resolution_km": None,
        "forecast_source_id": None,
        "forecast_source_label": None,
        "ocean_source": None,
        "truth_station_id": None,
        "truth_station_name": None,
        "source_field": "station_metadata",
        "provider": row.get("provider"),
        "network": row.get("network"),
        "station_kind": row.get("station_kind"),
        "priority": row.get("priority"),
        "latitude": numeric_value(row.get("latitude")),
        "longitude": numeric_value(row.get("longitude")),
        "depth_m": numeric_value(row.get("depth_m")),
        "source_time_coordinate_utc": bigquery_timestamp(row.get("last_sample_utc")),
        "qc_flag": row.get("qc_flag"),
        "freshness_status": row.get("freshness_status") or row.get("freshness_state"),
        "freshness_state": row.get("freshness_state") or (row.get("freshness_status") or "").upper(),
        "quality_score": numeric_value(row.get("quality_score")),
        "is_future": row.get("is_future"),
        "is_future_timestamp": row.get("is_future_timestamp") or row.get("is_future"),
        "is_qc_good": row.get("is_qc_good"),
        "variables_supported": variables_supported,
        "nearest_routes": row.get("nearest_routes") or [],
        "distance_to_route_nm": numeric_value(row.get("distance_to_route_nm")),
        "distance_to_palma": numeric_value(row.get("distance_to_palma")),
        "distance_to_ibiza": numeric_value(row.get("distance_to_ibiza")),
        "distance_to_menorca": numeric_value(row.get("distance_to_menorca")),
    }
    normalized["distance_to_menorca"] = numeric_value(row.get("distance_to_menorca"))
    # Dynamic filtering layer against local schema definition
    allowed_fields = {field["name"] for field in station_metadata_schema()}
    filtered_normalized = {k: v for k, v in normalized.items() if k in allowed_fields}
    filtered_normalized["row_hash"] = stable_row_hash(filtered_normalized)
    return filtered_normalized


def normalize_source_inventory_row(row, ingested_at_utc):
    sample_time_utc = bigquery_timestamp(row.get("sample_time_utc") or row.get("observed_at_utc"))
    observed_at_utc = bigquery_timestamp(row.get("observed_at_utc") or row.get("sample_time_utc"))
    available = row.get("available")
    if row.get("value") is not None:
        value = numeric_value(row.get("value"))
    elif available is None:
        value = None
    else:
        value = 1.0 if available else 0.0
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "source_inventory",
        "source_family": row.get("source_family") or "unknown",
        "run_date": row.get("run_date"),
        "run_id": row.get("run_id"),
        "ingested_at_utc": ingested_at_utc,
        "source_system": row.get("source_system") or row.get("provider"),
        "source_label": row.get("source_label") or row.get("station_name"),
        "route_id": None,
        "route_name": None,
        "station_id": row.get("station_id"),
        "station_name": row.get("station_name"),
        "reference_station_id": None,
        "reference_station_name": None,
        "variable": row.get("variable") or "source_status",
        "value": value,
        "units": row.get("units"),
        "sample_time_utc": sample_time_utc,
        "observed_at_utc": observed_at_utc,
        "forecast_created_at_utc": None,
        "target_time_utc": None,
        "target_local_time": None,
        "lead_time_hours": None,
        "resolution_km": numeric_value(row.get("resolution_km")),
        "forecast_source_id": None,
        "forecast_source_label": None,
        "ocean_source": None,
        "truth_station_id": None,
        "truth_station_name": None,
        "source_field": row.get("source_field") or "available",
        "dataset_url": row.get("dataset_url"),
        "provider": row.get("provider"),
        "network": row.get("network"),
        "station_kind": row.get("station_kind"),
        "priority": row.get("priority"),
        "latitude": numeric_value(row.get("latitude")),
        "longitude": numeric_value(row.get("longitude")),
        "depth_m": numeric_value(row.get("depth_m")),
        "source_time_coordinate_utc": bigquery_timestamp(row.get("source_time_coordinate_utc") or row.get("observed_at_utc")),
        "qc_flag": row.get("qc_flag"),
        "freshness_status": row.get("freshness_status") or row.get("freshness_state"),
        "freshness_state": row.get("freshness_state") or (row.get("freshness_status") or "").upper(),
        "quality_score": numeric_value(row.get("quality_score")),
        "is_future": row.get("is_future"),
        "is_future_timestamp": row.get("is_future_timestamp") or row.get("is_future"),
        "is_qc_good": row.get("is_qc_good"),
        "variables_supported": row.get("variables_supported") or [],
        "nearest_routes": row.get("nearest_routes") or [],
        "distance_to_route_nm": numeric_value(row.get("distance_to_route_nm")),
        "distance_to_palma": numeric_value(row.get("distance_to_palma")),
        "distance_to_ibiza": numeric_value(row.get("distance_to_ibiza")),
        "distance_to_menorca": numeric_value(row.get("distance_to_menorca")),
    }
    allowed_fields = {field["name"] for field in bigquery_schema()}
    filtered_normalized = {
        key: sanitize_float(value)
        for key, value in normalized.items()
        if key in allowed_fields
    }
    filtered_normalized["row_hash"] = stable_row_hash(filtered_normalized)
    return filtered_normalized


def stable_row_hash(row):
    payload = {key: row.get(key) for key in sorted(row) if key != "ingested_at_utc"}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return digest


def bigquery_schema():
    return [
        {"name": "schema_version", "type": "STRING", "mode": "REQUIRED"},
        {"name": "row_hash", "type": "STRING", "mode": "REQUIRED"},
        {"name": "record_type", "type": "STRING", "mode": "REQUIRED"},
        {"name": "source_family", "type": "STRING", "mode": "NULLABLE"},
        {"name": "run_date", "type": "DATE", "mode": "REQUIRED"},
        {"name": "run_id", "type": "STRING", "mode": "REQUIRED"},
        {"name": "ingested_at_utc", "type": "TIMESTAMP", "mode": "REQUIRED"},
        {"name": "source_system", "type": "STRING", "mode": "NULLABLE"},
        {"name": "source_label", "type": "STRING", "mode": "NULLABLE"},
        {"name": "route_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "route_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "station_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "station_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "reference_station_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "reference_station_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "variable", "type": "STRING", "mode": "REQUIRED"},
        {"name": "value", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "units", "type": "STRING", "mode": "NULLABLE"},
        {"name": "sample_time_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "observed_at_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "forecast_created_at_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "target_time_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "target_local_time", "type": "STRING", "mode": "NULLABLE"},
        {"name": "lead_time_hours", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "resolution_km", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "forecast_source_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "forecast_source_label", "type": "STRING", "mode": "NULLABLE"},
        {"name": "ocean_source", "type": "STRING", "mode": "NULLABLE"},
        {"name": "truth_station_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "truth_station_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "source_field", "type": "STRING", "mode": "NULLABLE"},
        {"name": "dataset_url", "type": "STRING", "mode": "NULLABLE"},
        {"name": "provider", "type": "STRING", "mode": "NULLABLE"},
        {"name": "network", "type": "STRING", "mode": "NULLABLE"},
        {"name": "station_kind", "type": "STRING", "mode": "NULLABLE"},
        {"name": "priority", "type": "STRING", "mode": "NULLABLE"},
        {"name": "latitude", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "longitude", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "depth_m", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "source_time_coordinate_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "qc_flag", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "freshness_status", "type": "STRING", "mode": "NULLABLE"},
        {"name": "freshness_state", "type": "STRING", "mode": "NULLABLE"},
        {"name": "quality_score", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "is_future", "type": "BOOL", "mode": "NULLABLE"},
        {"name": "is_future_timestamp", "type": "BOOL", "mode": "NULLABLE"},
        {"name": "is_qc_good", "type": "BOOL", "mode": "NULLABLE"},
        {"name": "variables_supported", "type": "STRING", "mode": "REPEATED"},
        {"name": "nearest_routes", "type": "STRING", "mode": "REPEATED"},
        {"name": "distance_to_route_nm", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "distance_to_palma", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "distance_to_ibiza", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "distance_to_menorca", "type": "FLOAT", "mode": "NULLABLE"},
    ]


def station_metadata_schema():
    return [
        {"name": "schema_version", "type": "STRING", "mode": "REQUIRED"},
        {"name": "row_hash", "type": "STRING", "mode": "REQUIRED"},
        {"name": "record_type", "type": "STRING", "mode": "REQUIRED"},
        {"name": "source_family", "type": "STRING", "mode": "NULLABLE"},
        {"name": "run_date", "type": "DATE", "mode": "REQUIRED"},
        {"name": "run_id", "type": "STRING", "mode": "REQUIRED"},
        {"name": "ingested_at_utc", "type": "TIMESTAMP", "mode": "REQUIRED"},
        {"name": "source_system", "type": "STRING", "mode": "NULLABLE"},
        {"name": "source_label", "type": "STRING", "mode": "NULLABLE"},
        {"name": "station_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "station_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "variable", "type": "STRING", "mode": "REQUIRED"},
        {"name": "value", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "units", "type": "STRING", "mode": "NULLABLE"},
        {"name": "sample_time_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "observed_at_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "provider", "type": "STRING", "mode": "NULLABLE"},
        {"name": "network", "type": "STRING", "mode": "NULLABLE"},
        {"name": "station_kind", "type": "STRING", "mode": "NULLABLE"},
        {"name": "priority", "type": "STRING", "mode": "NULLABLE"},
        {"name": "latitude", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "longitude", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "depth_m", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "source_time_coordinate_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "qc_flag", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "freshness_status", "type": "STRING", "mode": "NULLABLE"},
        {"name": "freshness_state", "type": "STRING", "mode": "NULLABLE"},
        {"name": "quality_score", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "is_future", "type": "BOOL", "mode": "NULLABLE"},
        {"name": "is_future_timestamp", "type": "BOOL", "mode": "NULLABLE"},
        {"name": "is_qc_good", "type": "BOOL", "mode": "NULLABLE"},
        {"name": "variables_supported", "type": "STRING", "mode": "REPEATED"},
        {"name": "nearest_routes", "type": "STRING", "mode": "REPEATED"},
        {"name": "distance_to_route_nm", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "distance_to_palma", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "distance_to_ibiza", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "distance_to_menorca", "type": "FLOAT", "mode": "NULLABLE"},
    ]


def schema_field_names(schema):
    return {field["name"] for field in schema}


def ensure_dataset(session, config: BigQueryConfig):
    dataset_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets/{config.dataset_id}"
    response = session.get(dataset_url, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
    if response.status_code == 200:
        return response.json()
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "datasetReference": {
            "projectId": config.project_id,
            "datasetId": config.dataset_id,
        },
        "location": config.location,
    }
    response = session.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets",
        json=payload,
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def ensure_table(session, config: BigQueryConfig):
    table_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets/{config.dataset_id}/tables/{config.table_id}"
    response = session.get(table_url, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
    if response.status_code == 200:
        return response.json()
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "tableReference": {
            "projectId": config.project_id,
            "datasetId": config.dataset_id,
            "tableId": config.table_id,
        },
        "schema": {"fields": bigquery_schema()},
        "timePartitioning": {"type": "DAY", "field": "run_date"},
        "clustering": {"fields": ["record_type", "route_id", "variable", "source_system"]},
    }
    response = session.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets/{config.dataset_id}/tables",
        json=payload,
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def ensure_station_metadata_table(session, config: BigQueryConfig):
    table_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets/{config.dataset_id}/tables/{config.table_id}"
    response = session.get(table_url, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
    if response.status_code == 200:
        existing = response.json()
        existing_fields = schema_field_names(existing.get("schema", {}).get("fields", []))
        desired_schema = station_metadata_schema()
        desired_fields = schema_field_names(desired_schema)
        if not desired_fields.issubset(existing_fields):
            patch_payload = {"schema": {"fields": desired_schema}}
            patch_response = session.patch(
                table_url,
                json=patch_payload,
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
            if patch_response.status_code not in (200, 201, 409):
                patch_response.raise_for_status()
            return patch_response.json() if patch_response.text else patch_payload
        return existing
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "tableReference": {
            "projectId": config.project_id,
            "datasetId": config.dataset_id,
            "tableId": config.table_id,
        },
        "schema": {"fields": station_metadata_schema()},
        "timePartitioning": {"type": "DAY", "field": "run_date"},
        "clustering": {"fields": ["record_type", "provider", "network", "station_id"]},
    }
    response = session.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets/{config.dataset_id}/tables",
        json=payload,
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def insert_rows(session, config: BigQueryConfig, rows: Sequence[dict]):
    if not rows:
        return {"status": "skipped", "failed_rows": 0, "insert_errors": []}

    insert_url = (
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}"
        f"/datasets/{config.dataset_id}/tables/{config.table_id}/insertAll"
    )
    failed_rows = 0
    insert_errors: List[dict] = []
    failed_row_samples: List[dict] = []
    error_messages: List[str] = []
    for batch_number, batch in enumerate(chunks(rows, INSERT_BATCH_SIZE), start=1):
        payload = {
            "skipInvalidRows": False,
            "ignoreUnknownValues": True,  # Swapped to True to prevent top-level HTTP 400 rejections
            "rows": [
                {
                    "insertId": row.get("row_hash"),
                    "json": row,
                }
                for row in batch
            ],
        }
        response = session.post(
            insert_url,
            json=payload,
            timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
        )
        body = _response_body(response)
        if response.status_code >= 400:
            error_message = _response_error_message(body, response.text, response.status_code)
            error_messages.append(error_message)
            failed_row_samples.extend(
                _failed_row_samples_for_batch(
                    batch,
                    batch_number=batch_number,
                    reason=error_message,
                    batch_errors=body.get("error") or body.get("errors") or [],
                )
            )
            return {
                "status": "error",
                "failed_rows": max(failed_rows, len(batch)),
                "insert_errors": insert_errors,
                "failed_row_samples": _dedupe_failed_row_samples(failed_row_samples),
                "error_messages": _dedupe_strings(error_messages),
                "response_status": response.status_code,
                "response_body": body or response.text,
            }
        batch_errors = body.get("insertErrors") or []
        if batch_errors:
            failed_rows += len(batch_errors)
            insert_errors.extend(
                _format_batch_errors(batch, batch_errors, batch_number=batch_number)
            )
            failed_row_samples.extend(
                _failed_row_samples_for_batch(
                    batch,
                    batch_number=batch_number,
                    reason="BigQuery insertAll partial failure",
                    batch_errors=batch_errors,
                )
            )
            error_messages.extend(_flatten_batch_error_messages(batch_errors))
    return {
        "status": "written" if not insert_errors else "partial_failure",
        "failed_rows": failed_rows,
        "insert_errors": insert_errors,
        "failed_row_samples": _dedupe_failed_row_samples(failed_row_samples),
        "error_messages": _dedupe_strings(error_messages),
    }


def chunks(rows: Sequence[dict], size: int):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _format_batch_errors(batch, batch_errors, *, batch_number):
    formatted = []
    for batch_error in batch_errors or []:
        if not isinstance(batch_error, dict):
            continue
        row_index = batch_error.get("index")
        row = batch[row_index] if isinstance(row_index, int) and 0 <= row_index < len(batch) else None
        errors = batch_error.get("errors") or []
        formatted.append(
            {
                "batch_number": batch_number,
                "index": row_index,
                "row_hash": (row or {}).get("row_hash"),
                "row_sample": _row_sample(row),
                "errors": errors,
                "messages": _flatten_error_messages(errors),
            }
        )
    return formatted


def _failed_row_samples_for_batch(batch, *, batch_number, reason, batch_errors=None):
    samples = []
    if batch_errors:
        for batch_error in batch_errors:
            if not isinstance(batch_error, dict):
                continue
            row_index = batch_error.get("index")
            row = batch[row_index] if isinstance(row_index, int) and 0 <= row_index < len(batch) else None
            samples.append(
                {
                    "batch_number": batch_number,
                    "index": row_index,
                    "reason": reason,
                    "row_hash": (row or {}).get("row_hash"),
                    "row_sample": _row_sample(row),
                    "error_messages": _flatten_error_messages(batch_error.get("errors") or []),
                }
            )
    if not samples:
        for row_index, row in enumerate(batch[:FAILED_ROW_SAMPLE_LIMIT]):
            samples.append(
                {
                    "batch_number": batch_number,
                    "index": row_index,
                    "reason": reason,
                    "row_hash": (row or {}).get("row_hash"),
                    "row_sample": _row_sample(row),
                    "error_messages": [reason],
                }
            )
    return samples[:FAILED_ROW_SAMPLE_LIMIT]


def _row_sample(row):
    if not isinstance(row, dict):
        return row
    keys = (
        "schema_version",
        "record_type",
        "run_date",
        "run_id",
        "provider",
        "source_system",
        "source_label",
        "station_id",
        "station_name",
        "reference_station_id",
        "reference_station_name",
        "route_id",
        "route_name",
        "variable",
        "value",
        "units",
        "sample_time_utc",
        "observed_at_utc",
        "source_time_coordinate_utc",
        "target_time_utc",
        "target_local_time",
        "forecast_created_at_utc",
        "quality_score",
        "freshness_status",
        "freshness_state",
        "qc_flag",
        "dataset_url",
        "latitude",
        "longitude",
    )
    return {key: row.get(key) for key in keys if key in row}


def _flatten_batch_error_messages(batch_errors):
    messages = []
    for batch_error in batch_errors or []:
        if not isinstance(batch_error, dict):
            continue
        messages.extend(_flatten_error_messages(batch_error.get("errors") or []))
    return messages


def _flatten_error_messages(errors):
    messages = []
    for error in errors or []:
        if isinstance(error, dict):
            message = error.get("message") or error.get("reason")
            if message:
                messages.append(str(message))
        elif error:
            messages.append(str(error))
    return messages


def _response_error_message(body, response_text, status_code):
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)
            details = error.get("errors") or []
            messages = _flatten_error_messages(details)
            if messages:
                return "; ".join(messages[:3])
        messages = _flatten_batch_error_messages(body.get("insertErrors") or [])
        if messages:
            return "; ".join(messages[:3])
    if isinstance(response_text, str) and response_text.strip():
        return response_text.strip()[:1000]
    return f"BigQuery insertAll returned HTTP {status_code}"


def _response_body(response):
    if not getattr(response, "text", None):
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw_response_text": response.text}


def _dedupe_failed_row_samples(samples):
    deduped = []
    seen = set()
    for sample in samples or []:
        fingerprint = json.dumps(sample, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(sample)
    return deduped


def _dedupe_strings(values):
    deduped = []
    seen = set()
    for value in values or []:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def authorized_bigquery_session():
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google_auth_default_project()
    return AuthorizedSession(creds)


def google_auth_default_project():
    import google.auth

    return google.auth.default(scopes=[BIGQUERY_SCOPE])


def current_timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def numeric_value(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def bigquery_timestamp(value):
    parsed = validation_archive.parse_timestamp(value)
    if not parsed:
        return None
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
