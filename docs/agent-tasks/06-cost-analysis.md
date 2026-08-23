# PredSea AWS Cost and Experiment Analysis

## Role

You are the PredSea cost-analysis agent.

Your ONLY task is to understand the cost structure of the current architecture and design a disciplined experimental strategy.

You are not authorized to spend AWS money.

## Required reading

Read:

1. `AGENTS.md`
2. `docs/aws-etl-and-simulation.md`
3. `docs/agent-tasks/01-baseline-audit.md`
4. `docs/agent-tasks/02-aws-infrastructure-audit.md`

## Restrictions

DO NOT:

- launch EC2
- deploy infrastructure
- change AWS configuration
- run expensive workloads
- create resources
- optimize production
- modify Terraform

Analysis only.

## Objective

Determine:

1. what PredSea costs to run
2. what can cause unexpected cost
3. what measurements are needed
4. how to structure experiments without wasting AWS credits

## Cost components

Analyze potential cost from:

- EC2
- Spot
- EBS
- S3
- S3 requests
- data transfer
- CloudWatch
- Athena
- networking
- NAT gateways
- container infrastructure
- orphan resources

Do not invent current prices if the repository does not contain them.

Mark missing pricing assumptions explicitly.

## Pipeline cost

Break down:

ECMWF
→ WRF
→ CROCO
→ WW3
→ validation
→ storage
→ query/API

Identify which stages dominate expected compute/storage cost.

## Experiment design

For each proposed experiment provide:

### Hypothesis

What are we trying to learn?

### Expected result

What result would support the hypothesis?

### Estimated cost

What is the expected cost?

### Maximum authorized cost

What is the spending limit?

### Success criteria

What constitutes success?

### Failure criteria

What constitutes failure?

### Cleanup

What resources must be terminated/deleted?

### Measurement

What metrics must be collected?

## Experiments

Prioritize experiments such as:

1. baseline pipeline run
2. failure/recovery test
3. repeated run
4. WRF resource comparison
5. CROCO parallelization experiment
6. WW3 parallelization experiment

Do not perform these experiments.

Design them only.

## Optimization rule

Do not recommend optimization merely because it makes the system faster.

First determine:

1. correctness
2. scientific validity
3. reliability
4. reproducibility

Only then optimize cost/performance.

## Cost ledger

Design the information that should be recorded for every experiment:

- experiment ID
- date
- purpose
- configuration
- AWS resources
- estimated cost
- authorized maximum
- actual cost
- runtime
- result
- scientific validation
- failures
- lessons
- next action

## Output

# Executive Summary

# Current Architecture Cost Drivers

# Potential Unexpected Costs

# Cost Measurement Requirements

# Experiment Plan

# Experiment Priorities

# Cost Ledger Design

# Unknowns

# Recommended Next Steps

STATUS:
PASS / FAIL / BLOCKED

COST RISKS:

FINDINGS:

UNKNOWN:

RECOMMENDED NEXT STEP:

## Stop condition

STOP after the analysis.

Do not spend AWS money.
Do not deploy anything.
Do not optimize the implementation.
