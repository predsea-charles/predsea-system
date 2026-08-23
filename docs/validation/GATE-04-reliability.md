# GATE-04 — Reliability and Recovery

## Purpose

Confirm that PredSea can handle expected failures
without corrupting forecasts or creating uncontrolled costs.

## Evidence required

Reliability audit covering:

- input failures
- WRF failures
- CROCO failures
- WW3 failures
- AWS failures
- Spot termination
- network failures
- storage failures
- container failures

## Required capabilities

We must understand:

- restart behavior
- retry behavior
- idempotency
- partial-output behavior
- completion markers
- duplicate-run behavior
- cleanup
- logging
- failure detection

## Critical question

Can the system distinguish:

INCOMPLETE

from:

COMPLETE

?

## PASS criteria

PASS only if:

- critical failure modes are understood
- partial outputs cannot silently become valid outputs
- duplicate execution behavior is understood
- cleanup is defined
- recovery is defined

## FAIL criteria

FAIL if:

- partial results can be mistaken for complete results
- retries can corrupt data
- duplicate runs can mix outputs
- failed AWS resources can remain running indefinitely

## BLOCKED criteria

BLOCKED if:

- failure behavior cannot be tested or understood

## Human decision

STATUS:

[ ] PASS
[ ] FAIL
[ ] BLOCKED

Decision:

Approved recovery strategy:

Notes:

Date:

Approved by:
