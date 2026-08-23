"""Small AWS adapters shared by the PredSea API and orchestration tasks."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3


def region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "eu-west-1"


def client(service: str):
    return boto3.client(service, region_name=region())


def get_secret(name: str, *, secrets_client=None) -> str | dict[str, Any]:
    """Read a PredSea secret. JSON secrets are returned as dictionaries."""
    secret_id = name if "/" in name else f"predsea/{name}"
    response = (secrets_client or client("secretsmanager")).get_secret_value(SecretId=secret_id)
    value = response.get("SecretString")
    if value is None:
        import base64
        value = base64.b64decode(response["SecretBinary"]).decode("utf-8")
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def upload_file(bucket: str, local_path: str, key: str, *, s3_client=None) -> None:
    (s3_client or client("s3")).upload_file(local_path, bucket, key)


def put_json(bucket: str, key: str, payload: Any, *, s3_client=None) -> None:
    (s3_client or client("s3")).put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


def query_athena(
    sql: str,
    *,
    parameters: list[str] | None = None,
    database: str | None = None,
    workgroup: str | None = None,
    output: str | None = None,
    timeout_seconds: int = 120,
    athena_client=None,
) -> list[dict[str, Any]]:
    """Execute Athena SQL and return dictionaries, without a PyAthena dependency."""
    athena = athena_client or client("athena")
    args: dict[str, Any] = {
        "QueryString": sql,
        "QueryExecutionContext": {"Database": database or os.getenv("PREDSEA_ATHENA_DATABASE", "predsea_validation")},
        "WorkGroup": workgroup or os.getenv("PREDSEA_ATHENA_WORKGROUP", "predsea"),
    }
    result_location = output or os.getenv("PREDSEA_ATHENA_OUTPUT")
    if result_location:
        args["ResultConfiguration"] = {"OutputLocation": result_location}
    if parameters:
        args["ExecutionParameters"] = parameters
    query_id = athena.start_query_execution(**args)["QueryExecutionId"]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in {"FAILED", "CANCELLED"}:
            reason = execution["Status"].get("StateChangeReason", state)
            raise RuntimeError(f"Athena query {query_id} {state.lower()}: {reason}")
        time.sleep(1)
    else:
        athena.stop_query_execution(QueryExecutionId=query_id)
        raise TimeoutError(f"Athena query {query_id} exceeded {timeout_seconds}s")

    paginator = athena.get_paginator("get_query_results")
    pages = paginator.paginate(QueryExecutionId=query_id)
    headers: list[str] | None = None
    records: list[dict[str, Any]] = []
    for page in pages:
        for row in page["ResultSet"].get("Rows", []):
            values = [item.get("VarCharValue") for item in row.get("Data", [])]
            if headers is None:
                headers = values
                continue
            values += [None] * (len(headers) - len(values))
            records.append(dict(zip(headers, values)))
    return records
