"""Portus model-point discovery and latest-position ingestion."""

from __future__ import annotations

import portus_client
import portus_config
import portus_parsers


def _unpack_payload(result):
    if isinstance(result, tuple) and len(result) == 2:
        return result
    return result, None


def discover_model_points(
    model_name=None,
    *,
    timeout=portus_config.DEFAULT_TIMEOUT_SECONDS,
    max_retries=portus_config.DEFAULT_MAX_RETRIES,
    backoff_seconds=portus_config.DEFAULT_BACKOFF_SECONDS,
    cache_dir=portus_config.RAW_CACHE_DIR,
    session=None,
    dry_run=False,
):
    model_name = model_name or portus_config.DEFAULT_MODEL_NAME
    if dry_run:
        return {
            "available": True,
            "source": "puertos_portus",
            "model_name": model_name,
            "dry_run": True,
        }

    url = portus_config.MODEL_POINT_DISCOVERY_ENDPOINT.format(model_name=model_name)
    payload_result = portus_client.fetch_json(
        url,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=f"model_points_{model_name}",
        session=session,
    )
    payload, raw_cache_path = _unpack_payload(payload_result)
    frame = portus_parsers.parse_model_points(payload)
    print(
        "Portus model points fetched: "
        f"endpoint={url} "
        f"model_name={model_name} "
        f"rows={len(frame)} "
        f"cache_path={raw_cache_path}",
        flush=True,
    )
    return {
        "available": True,
        "source": "puertos_portus",
        "model_name": model_name,
        "row_count": len(frame),
        "raw_cache_path": str(raw_cache_path) if raw_cache_path else None,
        "dataframe": frame,
        "records": frame.to_dict(orient="records"),
    }


def fetch_latest_position(
    model_point_id,
    *,
    station_code_for_verification=None,
    timeout=portus_config.DEFAULT_TIMEOUT_SECONDS,
    max_retries=portus_config.DEFAULT_MAX_RETRIES,
    backoff_seconds=portus_config.DEFAULT_BACKOFF_SECONDS,
    cache_dir=portus_config.RAW_CACHE_DIR,
    session=None,
    dry_run=False,
):
    if dry_run:
        return {
            "available": True,
            "source": "puertos_portus",
            "model_point_id": model_point_id,
            "dry_run": True,
        }

    url = portus_config.LATEST_POSITION_ENDPOINT.format(model_point_id=model_point_id)
    payload_result = portus_client.fetch_json(
        url,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=f"latest_position_{model_point_id}",
        session=session,
    )
    payload, raw_cache_path = _unpack_payload(payload_result)
    frame = portus_parsers.parse_last_positions(
        payload,
        model_point_id,
        station_code_for_verification=station_code_for_verification,
    )
    print(
        "Portus latest position fetched: "
        f"endpoint={url} "
        f"model_point_id={model_point_id} "
        f"rows={len(frame)} "
        f"cache_path={raw_cache_path}",
        flush=True,
    )
    return {
        "available": True,
        "source": "puertos_portus",
        "model_point_id": model_point_id,
        "station_code_for_verification": station_code_for_verification,
        "row_count": len(frame),
        "raw_cache_path": str(raw_cache_path) if raw_cache_path else None,
        "dataframe": frame,
        "records": frame.to_dict(orient="records"),
    }


def fetch_portus_predictions(
    model_name=None,
    *,
    model_point_limit=None,
    fetch_latest_positions=portus_config.DEFAULT_FETCH_LATEST_POSITIONS,
    timeout=portus_config.DEFAULT_TIMEOUT_SECONDS,
    max_retries=portus_config.DEFAULT_MAX_RETRIES,
    backoff_seconds=portus_config.DEFAULT_BACKOFF_SECONDS,
    cache_dir=portus_config.RAW_CACHE_DIR,
    session=None,
    dry_run=False,
):
    discovery = discover_model_points(
        model_name=model_name,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        session=session,
        dry_run=dry_run,
    )
    if discovery.get("dry_run"):
        return {
            "available": True,
            "source": "puertos_portus",
            "model_name": discovery["model_name"],
            "dry_run": True,
        }

    frame = discovery.get("dataframe")
    records = discovery.get("records", [])
    if model_point_limit is None:
        model_point_limit = portus_config.DEFAULT_MODEL_POINT_LIMIT
    selected = records[:model_point_limit] if model_point_limit else records

    latest_positions = {}
    errors = {}
    if fetch_latest_positions:
        for record in selected:
            model_point_id = record.get("model_point_id")
            try:
                latest_result = fetch_latest_position(
                    model_point_id,
                    station_code_for_verification=record.get("station_code_for_verification"),
                    timeout=timeout,
                    max_retries=max_retries,
                    backoff_seconds=backoff_seconds,
                    cache_dir=cache_dir,
                    session=session,
                    dry_run=dry_run,
                )
                records_for_point = latest_result.get("records", [])
                if records_for_point:
                    latest_positions[str(model_point_id)] = records_for_point
            except Exception as error:
                errors[str(model_point_id)] = str(error)

    status = "matched_successfully" if records else "unavailable"
    return {
        "available": bool(records),
        "source": "puertos_portus",
        "model_name": discovery["model_name"],
        "row_count": len(records),
        "model_points": records,
        "latest_positions": latest_positions,
        "errors": errors,
        "lineage": {
            "source": "puertos_portus_predictions" if records else None,
            "status": status,
            "model_name": discovery["model_name"],
            "model_point_count": len(records),
            "latest_position_count": len(latest_positions),
            "latest_positions_enabled": bool(fetch_latest_positions),
        },
    }
