# GATE-03 — Scientific Validation

## Purpose

Define and approve what "scientifically valid" means
before interpreting production outputs.

## Critical rule

A successful model execution does NOT mean
the model is scientifically valid.

Technical success and scientific validity are separate.

## Evidence required

Scientific validation design must define:

- input validation
- WRF validation
- CROCO validation
- WW3 validation
- end-to-end validation

## CROCO

For every CROCO regional domain we must know:

- correct grid
- correct grid version
- correct forcing
- correct initial conditions
- correct boundary conditions
- correct atmospheric forcing
- correct ocean forcing
- correct timestamps
- correct units
- expected outputs
- validation criteria

## Validation criteria

Every criterion must be classified as:

ESTABLISHED

PROPOSED

SCIENTIFIC APPROVAL REQUIRED

## External validation

Where appropriate, identify:

- observations
- reanalysis
- reference datasets
- climatology
- independent datasets

## Scientific thresholds

No threshold may be treated as authoritative
unless scientifically approved.

## PASS criteria

PASS only when:

- required validation criteria are defined
- scientific owner approves required thresholds
- reference datasets are identified
- CROCO-specific validation is defined
- end-to-end validation is defined

## FAIL criteria

FAIL if:

- model success is being treated as scientific validation
- critical scientific criteria are undefined
- critical thresholds are invented or unsupported

## BLOCKED criteria

BLOCKED if:

- required scientific decisions cannot yet be made
- required reference datasets are unavailable

## Human decision

STATUS:

[ ] PASS
[ ] FAIL
[ ] BLOCKED

Scientific owner:

Approved criteria:

Rejected criteria:

Open scientific questions:

Date:

Approved by:
