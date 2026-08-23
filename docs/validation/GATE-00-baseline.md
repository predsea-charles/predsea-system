# GATE-00 — Baseline Understanding

## Purpose

Confirm that we understand what PredSea actually does today.

This gate must pass before implementation changes begin.

## Evidence required

The following audits must exist:

- `01-baseline-audit`
- AWS audit
- ETL audit
- CROCO audit

## Required conclusions

We must know:

- actual pipeline architecture
- actual repository structure
- actual WRF execution
- actual CROCO execution
- actual WW3 execution
- actual AWS orchestration
- actual storage flow
- actual validation flow
- actual API/query flow

## Documentation consistency

Every major discrepancy between:

documentation

and

actual implementation

must be identified.

## Critical questions

- Is the documented pipeline actually implemented?
- Are there undocumented components?
- Are there undocumented dependencies?
- Are there dangerous assumptions?
- Are there missing tests?
- Are there unknown scientific assumptions?

## PASS criteria

PASS only if:

- baseline audit is complete
- major architecture discrepancies are known
- critical unknowns are documented
- no critical unexplained architectural issue remains

## FAIL criteria

FAIL if:

- major parts of the system remain unknown
- architecture documentation materially disagrees with implementation
- critical dependencies are unexplained
- important execution paths cannot be traced

## BLOCKED criteria

BLOCKED if:

- required repository information is inaccessible
- required architecture documentation is missing
- scientific/technical information is unavailable

## Human decision

STATUS:

[ ] PASS
[ ] FAIL
[ ] BLOCKED

Decision:

Notes:

Date:

Approved by:
