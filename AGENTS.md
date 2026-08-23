# PredSea Agent Instructions

## Mission

PredSea is a marine forecasting system:

ECMWF
  ↓
WRF
  ↓
CROCO
  ↓
WW3
  ↓
Validation
  ↓
S3 / Athena / API

## Source of truth

Before making recommendations:

1. Read `aws-etl-and-simulation.md`.
2. Inspect the actual repository.
3. Never assume the documentation is correct.
4. Report discrepancies between documentation and implementation.

## CROCO

PredSea currently uses five regional CROCO domains.

Never:
- replace canonical grids without approval
- change grid versions silently
- change MPI decomposition without approval
- modify forcing/boundary-condition logic without tests
- declare CROCO scientifically valid merely because it exits successfully

## Safety

Agents must NOT:

- enable EventBridge
- launch expensive AWS workloads without explicit approval
- launch multiple EC2 workers without approval
- modify production infrastructure merely to test an idea
- delete canonical data
- make unreviewed architectural changes

## Engineering rules

Prefer:

- small changes
- reviewable diffs
- reproducible experiments
- exact file/function/line references
- tests before claims
- evidence before conclusions

Distinguish:

1. Code correctness
2. Pipeline correctness
3. Scientific correctness

## Scientific rules

Never invent scientific acceptance thresholds.

If a threshold is missing:

1. identify the missing criterion
2. propose a candidate only if useful
3. explicitly mark it as requiring scientific approval

## AWS budget

AWS credits are finite.

Every paid experiment requires:

- hypothesis
- expected result
- estimated cost
- maximum authorized cost
- success criteria
- failure criteria
- cleanup plan

## Required report

Every task ends with:

STATUS:
PASS / FAIL / BLOCKED

FINDINGS:

EVIDENCE:

RISKS:

UNKNOWN:

CHANGES MADE:

TESTS RUN:

AWS / COST IMPACT:

RECOMMENDED NEXT STEP:
