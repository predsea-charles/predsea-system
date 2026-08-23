# GATE-02 — ETL and Data Contracts

## Purpose

Confirm that the data moving through PredSea can be trusted
at the pipeline/data-contract level.

## Evidence required

- ETL audit
- ECMWF input analysis
- CMEMS input analysis
- WRF input/output analysis
- CROCO forcing analysis
- WW3 forcing analysis

## Required conclusions

For every major dataset we know:

- source
- producer
- consumer
- location
- format
- variables
- units
- coordinates
- timestamps
- spatial coverage
- temporal coverage
- version
- completeness requirements

## Time consistency

Must be understood across:

ECMWF
→ WRF
→ CROCO
→ WW3

No unexplained timestamp transformations.

## Staleness

The pipeline must have a defensible mechanism for preventing:

- stale forcing
- stale forecast files
- previous-run contamination
- partial downloads

## Region integrity

The pipeline must not silently mix:

- regions
- grids
- forcing
- forecast periods

## PASS criteria

PASS only if:

- critical data contracts are understood
- timestamp handling is understood
- stale-data risks are controlled
- region integrity is controlled
- missing contracts are explicitly documented

## FAIL criteria

FAIL if:

- wrong-period data can silently enter the pipeline
- stale forcing can be consumed
- region/grid mismatch can occur silently
- critical units/coordinates are ambiguous

## BLOCKED criteria

BLOCKED if:

- required source specifications are unavailable
- scientific ownership is required to resolve a critical contract

## Human decision

STATUS:

[ ] PASS
[ ] FAIL
[ ] BLOCKED

Decision:

Scientific decisions required:

Notes:

Date:

Approved by:
