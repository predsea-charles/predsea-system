# PredSea Scientific Validation Design

## Role

You are the PredSea scientific-validation agent.

Your ONLY task is to define and document what must be demonstrated before PredSea can claim that its forecast outputs are scientifically credible.

You are not authorized to declare the system scientifically valid.

## Required reading

Read:

1. `AGENTS.md`
2. `docs/aws-etl-and-simulation.md`
3. `docs/agent-tasks/01-baseline-audit.md`
4. `docs/agent-tasks/03-etl-data-audit.md`
5. `docs/agent-tasks/03a-croco-audit.md`

## Restrictions

DO NOT:

- modify source code
- modify model configuration
- modify grids
- modify forcing
- run expensive simulations
- invent scientific thresholds
- declare scientific validity
- change architecture

## Objective

Define a scientifically defensible validation framework for:

WRF
  ↓
CROCO
  ↓
WW3

The framework must distinguish:

1. technically completed
2. data-contract correct
3. scientifically plausible
4. scientifically validated

These are NOT equivalent.

## Validation layers

Design validation at these levels:

### Layer 1 — Input validation

Determine whether required input data are:

- present
- complete
- correctly dated
- correctly located
- correctly versioned
- internally consistent

### Layer 2 — WRF validation

Determine what should be checked for:

- atmospheric variables
- spatial coverage
- temporal coverage
- units
- metadata
- forcing suitability for CROCO/WW3

Do not invent numerical acceptance thresholds.

### Layer 3 — CROCO validation

Determine what should be checked for:

- temperature
- salinity
- currents
- sea level
- spatial structure
- temporal behavior
- boundary behavior
- forcing consistency
- physical plausibility

Identify which criteria require external observational/reanalysis references.

### Layer 4 — WW3 validation

Determine what should be checked for:

- significant wave height
- wave period
- wave direction
- wind-wave consistency
- spatial structure
- temporal behavior
- physical plausibility

### Layer 5 — End-to-end validation

Determine whether:

WRF
→ CROCO
→ WW3

uses consistent:

- forecast period
- timestamps
- geography
- forcing
- units
- metadata

## Evidence categories

Every criterion must be classified as:

ESTABLISHED

The repository/documentation already defines it.

PROPOSED

A reasonable candidate criterion that requires review.

SCIENTIFIC APPROVAL REQUIRED

The system cannot responsibly choose the criterion automatically.

## Validation matrix

Create a table containing:

- component
- variable/output
- validation question
- evidence required
- reference dataset if applicable
- metric if known
- threshold if established
- threshold status
- automated/manual
- scientific approval required

## Critical rule

Never convert:

"the model completed"

into:

"the model is scientifically valid."

## Human approval

Explicitly identify every criterion that requires scientific-owner approval.

## Output

# Scientific Validation Philosophy

# Validation Layers

# WRF Criteria

# CROCO Criteria

# WW3 Criteria

# End-to-End Criteria

# Observational/Reference Data Requirements

# Validation Matrix

# Proposed Criteria

# Scientific Approval Required

# Unknowns

# Recommended Next Steps

STATUS:
PASS / FAIL / BLOCKED

SCIENTIFIC DECISIONS REQUIRED:

PROPOSED CRITERIA:

ESTABLISHED CRITERIA:

UNKNOWN:

RECOMMENDED NEXT STEP:

## Stop condition

STOP after designing the validation framework.

Do not implement validation.
Do not modify the model.
Do not declare scientific validity.
