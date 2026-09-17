"""
daily_trigger/handler.py — submits the ECMWF -> WRF -> WW3 Batch job chain,
replicating run_all_regions.sh, but runnable from a scheduled Lambda instead
of a human at a laptop.

Trigger: EventBridge Scheduler, cron(30 0 * * ? *) = 00:30 UTC daily.

Safety behavior added beyond the original script:
  - Refuses to submit if a run for today's run_date is already
    SUBMITTED/PENDING/RUNNABLE/STARTING/RUNNING on the target queue. This
    guards against duplicate runs from a Scheduler retry or an accidental
    manual re-invoke landing on the same day — a risk the original script
    didn't have to worry about because a human was always running it once,
    on purpose.
  - forecast_hours is fixed at 72 by default (not read from argv the way
    the shell script took $1), specifically because a manual mistake
    (launching 82h instead of 72h) already happened once in this project.
    An event payload can still override it for deliberate manual test
    invokes — see below.

Manual test invoke (bypasses the schedule, useful for validating changes):
    aws lambda invoke --function-name predsea-daily-trigger \\
      --payload '{"forecast_hours": 72}' --cli-binary-format raw-in-base64-out \\
      /tmp/out.json
    cat /tmp/out.json
"""
from __future__ import annotations

import datetime as dt
import json
import os

import boto3

REGION_AWS = os.environ.get("PREDSEA_AWS_REGION", "eu-west-1")
JOB_QUEUE = os.environ.get("PREDSEA_JOB_QUEUE", "predsea-models-canary")
DEFAULT_FORECAST_HOURS = int(os.environ.get("PREDSEA_DEFAULT_FORECAST_HOURS", "72"))

# Batch job statuses that mean "already in flight, don't submit another".
ACTIVE_STATUSES = ["SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING"]

batch = boto3.client("batch", region_name=REGION_AWS)


def _today_utc() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d")


def _any_active_job_for_run(run_date: str, forecast_hours: int) -> str | None:
    """
    Return a description of the first active job found for this run_date's
    expected job names (ecmwf-<h>h / wrf-<h>h / ww3-<h>h), or None if clear.

    This is a best-effort duplicate guard based on job NAME, since Batch
    doesn't enforce name uniqueness itself. It only catches jobs already
    submitted through this same naming convention.
    """
    expected_names = {
        f"ecmwf-{forecast_hours}h",
        f"wrf-{forecast_hours}h",
        f"ww3-{forecast_hours}h",
    }
    for status in ACTIVE_STATUSES:
        paginator = batch.get_paginator("list_jobs")
        for page in paginator.paginate(jobQueue=JOB_QUEUE, jobStatus=status):
            for job in page.get("jobSummaryList", []):
                if job["jobName"] in expected_names:
                    return (
                        f"Job '{job['jobName']}' (id={job['jobId']}) is already "
                        f"{status} on queue {JOB_QUEUE}."
                    )
    return None


def handler(event, context):
    event = event or {}
    forecast_hours = int(event.get("forecast_hours", DEFAULT_FORECAST_HOURS))
    run_date = event.get("run_date", _today_utc())
    run_id = f"{run_date}T0000Z-{forecast_hours}h"

    print(f"predsea daily trigger: forecast_hours={forecast_hours} "
          f"run_date={run_date} run_id={run_id} queue={JOB_QUEUE}")

    guard_hit = _any_active_job_for_run(run_date, forecast_hours)
    if guard_hit:
        msg = f"REFUSING to submit — duplicate run detected: {guard_hit}"
        print(msg)
        return {"submitted": False, "reason": msg}

    ecmwf = batch.submit_job(
        jobName=f"ecmwf-{forecast_hours}h",
        jobQueue=JOB_QUEUE,
        jobDefinition="predsea-ecmwf-hpc",
        parameters={"run_date": run_date, "lead_hours": str(forecast_hours)},
    )
    ecmwf_id = ecmwf["jobId"]
    print(f"ECMWF job: {ecmwf_id}")

    wrf = batch.submit_job(
        jobName=f"wrf-{forecast_hours}h",
        jobQueue=JOB_QUEUE,
        jobDefinition="predsea-wrf-hpc",
        parameters={"run_date": run_date, "run_id": run_id, "forecast_hours": str(forecast_hours)},
        dependsOn=[{"jobId": ecmwf_id}],
    )
    wrf_id = wrf["jobId"]
    print(f"WRF job: {wrf_id} (depends on ECMWF)")

    ww3 = batch.submit_job(
        jobName=f"ww3-{forecast_hours}h",
        jobQueue=JOB_QUEUE,
        jobDefinition="predsea-ww3-hpc",
        parameters={
            # NOTE: still "alboran_1km" — matches run_all_regions.sh as of
            # this writing. Update this alongside the shell script once the
            # western_mediterranean_1km WW3 region config is built and
            # canary-validated. Do not change only one of the two places.
            "region": "alboran_1km",
            "forecast_hours": str(forecast_hours),
            "mpi_ranks": "64",
            "run_date": run_date,
            "run_id": run_id,
        },
        dependsOn=[{"jobId": wrf_id}],
    )
    ww3_id = ww3["jobId"]
    print(f"WW3 job: {ww3_id} (depends on WRF)")

    result = {
        "submitted": True,
        "run_date": run_date,
        "run_id": run_id,
        "forecast_hours": forecast_hours,
        "job_ids": {"ecmwf": ecmwf_id, "wrf": wrf_id, "ww3": ww3_id},
    }
    print(json.dumps(result))
    return result
