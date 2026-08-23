# GATE-01 — AWS Infrastructure Safety

## Purpose

Confirm that the AWS infrastructure is understood and safe enough
to proceed toward controlled experimentation.

## Evidence required

AWS infrastructure audit must exist.

## Required conclusions

We must understand:

- EC2 configuration
- Spot configuration
- IAM
- S3
- EBS
- networking
- containers
- logging
- Athena
- EventBridge
- secrets
- cleanup behavior

## Security

No known critical:

- credential exposure
- excessive IAM permissions
- public storage exposure
- unsafe networking
- uncontrolled secrets

## Cost safety

We must know:

- which resources cost money
- how they are created
- how they terminate
- how orphan resources are detected
- how an experiment is capped

## Scheduling

Automated scheduling must remain disabled unless explicitly approved.

## Cleanup

We must have a credible procedure for:

- EC2 termination
- EBS cleanup
- temporary resource cleanup
- failed-run cleanup
- preventing orphan resources

## PASS criteria

PASS only if:

- AWS architecture is understood
- critical security issues are resolved or explicitly accepted
- cost risks are understood
- cleanup is understood
- no uncontrolled scheduler is active

## FAIL criteria

FAIL if:

- critical security issue exists
- AWS costs cannot be bounded
- cleanup is unreliable
- automated execution can unexpectedly create expensive workloads

## BLOCKED criteria

BLOCKED if:

- AWS configuration cannot be inspected
- required permissions/information are unavailable

## Human decision

STATUS:

[ ] PASS
[ ] FAIL
[ ] BLOCKED

Decision:

Approved AWS experiment budget:

Notes:

Date:

Approved by:
