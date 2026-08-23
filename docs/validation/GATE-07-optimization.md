# GATE-07 — Performance and Cost Optimization

## Purpose

Authorize performance and cost optimization only after
correctness, science, and reliability have been established.

## Required gates

Must have:

- GATE-00 PASS
- GATE-01 PASS
- GATE-02 PASS
- GATE-03 PASS
- GATE-04 PASS
- GATE-05 PASS

## Optimization targets

Potential areas:

- WRF
- CROCO MPI
- CROCO domain decomposition
- WW3 MPI
- EC2 instance type
- Spot strategy
- storage
- data movement
- pipeline parallelism
- caching

## Rule

Never optimize a component whose correctness
or scientific validity has not been established.

## Every optimization experiment requires

Hypothesis:

Baseline:

Change:

Expected improvement:

Maximum cost:

Success criteria:

Failure criteria:

Scientific regression criteria:

Cleanup:

Actual result:

Actual cost:

Decision:

## Scientific regression

Optimization must not degrade:

- scientific validity
- reproducibility
- data integrity
- validation results

## PASS criteria

Optimization demonstrates measurable improvement
without scientific or reliability regression.

## FAIL criteria

Optimization causes:

- scientific degradation
- reliability degradation
- data corruption
- unacceptable reproducibility loss
- cost increase without corresponding benefit

## Human decision

STATUS:

[ ] PASS
[ ] FAIL
[ ] BLOCKED

Approved optimization:

Baseline:

Result:

Scientific regression check:

Date:

Approved by:
