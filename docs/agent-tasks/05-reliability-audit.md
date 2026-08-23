# PredSea Reliability, Failure Recovery and Idempotency Audit

## Role

You are the PredSea reliability audit agent.

Your ONLY task is to determine whether the forecasting pipeline behaves safely when things go wrong.

You are an auditor, not an implementer.

## Required reading

Read:

1. `AGENTS.md`
2. `docs/aws-etl-and-simulation.md`
3. `docs/agent-tasks/01-baseline-audit.md`
4. `docs/agent-tasks/02-aws-infrastructure-audit.md`
5. `docs/agent-tasks/03-etl-data-audit.md`

## Restrictions

DO NOT:

- modify code
- deploy infrastructure
- launch EC2
- run expensive simulations
- intentionally break production
- delete data
- optimize
- implement fixes

## Objective

Determine whether PredSea can safely handle failures and retries.

## Failure scenarios

Analyze:

### Input failure

- ECMWF unavailable
- CMEMS unavailable
- incomplete download
- corrupt input
- stale input

### WRF failure

- process crash
- container failure
- disk exhaustion
- incomplete output
- timeout

### CROCO failure

- MPI failure
- rank failure
- memory failure
- missing forcing
- invalid input
- incomplete NetCDF
- partial output

### WW3 failure

- missing forcing
- process failure
- partial output
- invalid output

### AWS failure

- Spot termination
- EC2 failure
- network failure
- S3 failure
- container failure
- IAM failure

## Idempotency

Determine whether repeating a forecast:

- overwrites valid data
- creates duplicate data
- mixes old/new files
- creates ambiguous completion state
- safely resumes
- safely restarts

## Atomicity

Determine whether the system distinguishes:

INCOMPLETE

from:

COMPLETE

For example, inspect whether completion markers, manifests, checksums, or equivalent mechanisms exist.

## Restart behavior

Determine:

- what can be restarted
- what must be rerun
- whether partial outputs can be trusted
- whether stages can be independently resumed
- whether a failed stage contaminates downstream stages

## Recovery

Determine whether there is a defined recovery procedure for each major failure.

## Observability

Inspect:

- logs
- error messages
- exit codes
- metrics
- CloudWatch
- S3 manifests
- run identifiers
- forecast identifiers
- timestamps

Determine whether an operator can answer:

"What happened to forecast X?"

## Duplicate execution

Determine what happens if the same forecast runs twice.

## Evidence

Every finding must include:

- Finding ID
- Severity
- Failure scenario
- File/resource
- Line number if available
- Current behavior
- Risk
- Evidence
- Recommended next step

## Output

# Executive Summary

# Failure Matrix

# Input Failures

# WRF Failures

# CROCO Failures

# WW3 Failures

# AWS Failures

# Idempotency

# Atomicity

# Restartability

# Recovery

# Observability

# Duplicate Execution

# Findings

# Unknowns

# Recommended Next Steps

STATUS:
PASS / FAIL / BLOCKED

CRITICAL RISKS:

FINDINGS:

UNKNOWN:

RECOMMENDED NEXT STEP:

## Stop condition

STOP after the audit.

Do not implement fixes.
