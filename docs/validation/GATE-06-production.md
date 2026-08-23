# GATE-06 — Production Readiness

## Purpose

Determine whether PredSea is ready for controlled production use.

## Required gates

Must have:

- GATE-00 PASS
- GATE-01 PASS
- GATE-02 PASS
- GATE-03 PASS
- GATE-04 PASS
- GATE-05 PASS

## Required evidence

### Engineering

- [ ] reproducible deployment
- [ ] configuration documented
- [ ] dependencies documented
- [ ] tests passing

### Data

- [ ] input contracts validated
- [ ] output contracts validated
- [ ] freshness validated

### CROCO

- [ ] all five domains validated
- [ ] grids validated
- [ ] forcing validated
- [ ] initial conditions validated
- [ ] boundary conditions validated
- [ ] scientific criteria passed

### Reliability

- [ ] restart behavior tested
- [ ] failure behavior tested
- [ ] duplicate execution understood
- [ ] cleanup tested

### AWS

- [ ] cost understood
- [ ] permissions reviewed
- [ ] orphan-resource prevention tested
- [ ] scheduling explicitly approved

### Scientific

- [ ] validation evidence reviewed
- [ ] scientific owner approves results

## PASS criteria

All required evidence exists and has been reviewed.

## FAIL criteria

Any critical production requirement is unresolved.

## BLOCKED criteria

A required scientific, engineering, or operational decision is unavailable.

## Human decision

STATUS:

[ ] PASS
[ ] FAIL
[ ] BLOCKED

Production scope:

Approved configuration:

Scientific approval:

Operational approval:

Date:

Approved by:
