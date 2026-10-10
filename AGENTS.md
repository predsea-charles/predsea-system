# PredSea Agent Instructions

## Mission

PredSea is a marine forecasting system:

ECMWF
  ↓
WRF  (AWS Batch, predsea-models-canary queue)
  ↓ (wind forcing generated here — wind.nc uploaded to S3 forcing/ww3/)
WW3  (AWS Batch, predsea-models-canary queue)
  ↓
Validation
  ↓
S3 / Athena / API (App Runner)

Active region: `western_mediterranean_2km`

CROCO has been removed from the pipeline.

## Source of truth

Before making recommendations:

1. Read `docs/aws-etl-and-simulation.md`.
2. Inspect the actual repository.
3. Never assume the documentation is correct.
4. Report discrepancies between documentation and implementation.

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
