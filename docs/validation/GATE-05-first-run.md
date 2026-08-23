# GATE-05 — First Paid Experiment

## Purpose

Authorize exactly one controlled AWS experiment.

## Experiment

Experiment ID:

EXP-001

## Hypothesis

The complete PredSea pipeline can execute successfully
for the defined forecast period using the approved configuration.

## Configuration

WRF:

CROCO:

WW3:

AWS:

Instance:

Spot/on-demand:

MPI:

## Forecast period

Start:

End:

Duration:

## Estimated cost

Estimated:

## Maximum authorized cost

Maximum:

## Success criteria

Technical:

- [ ]

Data:

- [ ]

CROCO:

- [ ]

WW3:

- [ ]

Scientific:

- [ ]

End-to-end:

- [ ]

## Failure criteria

The experiment is considered failed if:

- [ ]
- [ ]
- [ ]

## Cleanup

After the experiment:

- EC2 terminated
- EBS handled
- temporary resources removed
- no orphan resources
- EventBridge remains disabled unless explicitly approved

## Observability

Record:

- start time
- end time
- AWS resources
- logs
- runtime
- actual cost
- failures
- outputs
- validation results

## PASS criteria

The experiment may proceed only if:

- GATE-00 PASS
- GATE-01 PASS
- GATE-02 PASS
- GATE-03 PASS
- GATE-04 PASS
- maximum cost is explicitly approved
- cleanup is understood

## Human authorization

AUTHORIZED TO SPEND:

[ ] YES
[ ] NO

Maximum authorized cost:

$

Approved configuration:

Approved by:

Date:

## After experiment

Actual cost:

Actual runtime:

Result:

Scientific result:

Failures:

Lessons:

Next action:
