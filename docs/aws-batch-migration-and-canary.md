# PredSea AWS Batch Migration and Canary Plan

Last verified: 2026-08-24  
Region: `eu-west-1`  
Status: implementation and canary preparation; not production-ready

## Executive summary

PredSea is moving its numerical forecast execution toward an AWS-native, independently observable model chain:

```text
ECMWF + immutable static grids
              |
              v
             WRF
            /   \
           v     v
        CROCO   WW3
           \     /
            v   v
        validation
            |
            v
    S3 / Athena / API
```

The immediate objective is deliberately smaller than production: prove one six-hour Alboran run through WRF, CROCO, and WW3 on a Spot-only AWS Batch queue. A successful process exit is not enough. Each stage must consume the intended immutable inputs, publish the expected outputs and success marker, retain usable logs, respect its timeout, and return compute to zero.

Automated scheduling remains disabled. Scientific validity is outside this infrastructure canary and requires separately approved acceptance criteria.

## North star

The north star is a reproducible daily forecast platform in which:

- every run has a unique run ID and traceable input, image, grid, configuration, and output versions;
- atmospheric and ocean inputs are validated before expensive compute starts;
- WRF, CROCO, and WW3 are separate, restartable jobs with explicit dependencies;
- canonical static data is immutable and promoted through controlled tooling;
- compute scales from zero, prefers Spot capacity, and returns to zero after every terminal outcome;
- logs and manifests make failures diagnosable without logging into a worker;
- technical, pipeline, and scientific validation are reported separately;
- production automation is enabled only after bounded manual canaries pass consistently.

The intended production horizon remains 72 hours over five regions. The six-hour, one-region canary is evidence toward that target, not a substitute for it.

## Production regions

The Batch design must ultimately support all five canonical 1 km domains. Alboran is only the first canary, not the only intended region.

| Region | Region ID | Bounding box (west, east, south, north) | Compiled CROCO rho shape | Present readiness |
|---|---|---|---|---|
| Alboran Sea | `alboran_1km` | -6.0, -1.0, 35.0, 37.5 | 501 × 251 | CROCO `v1.0` grid and WW3 `mod_def.ww3` staged; selected canary |
| Algerian Basin | `algerian_1km` | -1.0, 8.5, 35.0, 38.0 | 951 × 301 | CROCO `v1.0` grid present; WW3 model definition missing |
| Gulf of Lion | `gulf_of_lion_1km` | 2.0, 6.5, 41.5, 43.3 | 500 × 200 | CROCO `v1.0` grid present; WW3 model definition missing |
| Balearic Sea | `balearic_1km` | 0.5, 5.5, 37.5, 41.5 | 501 × 401 | CROCO `v1.0` grid present; WW3 model definition missing |
| Tyrrhenian Sea | `tyrrhenian_1km` | 7.5, 14.0, 38.0, 44.5 | 650 × 651 | CROCO `v1.0` grid present; WW3 model definition missing |

The shapes above are compiled runtime contracts from the regional profiles. Grid dimensions, MPI decomposition, and canonical grid versions must not be changed implicitly.

## What is deployed today

Terraform under `infra/aws` describes:

- encrypted, versioned S3 storage in `predsea-daily-outputs`;
- ECR repositories for API, orchestrator, WRF, CROCO, and WW3 images;
- a privileged CodeBuild project that reads `codebuild-source/source.zip`;
- managed AWS Batch Spot and On-Demand compute environments using `c6i.32xlarge`;
- 300 GiB encrypted gp3 worker disks and IMDSv2 enforcement;
- a normal Batch queue with Spot followed by On-Demand fallback;
- a separate canary queue containing only the Spot compute environment;
- WRF, CROCO, and WW3 job definitions with CloudWatch logging;
- App Runner, ECS/Fargate orchestration, Athena, Glue, IAM, and Secrets Manager resources;
- an EventBridge Scheduler schedule created with `DISABLED` as its default state.

Verified AWS state on 2026-08-24:

| Control | Observed state |
|---|---|
| `predsea-daily` schedule | `DISABLED` |
| Spot compute environment | `VALID`, min 0, desired 0, max 128 vCPUs |
| On-Demand compute environment | `VALID`, min 0, desired 0, max 128 vCPUs |
| WRF/CROCO/WW3 ECR images | no image present yet |
| Current image build | running on a one-build `BUILD_GENERAL1_XLARGE` override |

The XLARGE override is temporary. The persistent CodeBuild project remains `BUILD_GENERAL1_LARGE`.

## Source-of-truth discrepancy

`docs/aws-etl-and-simulation.md` describes the daily numerical workload as one directly launched EC2 Spot instance running WRF and all five CROCO and WW3 regions sequentially. The repository now also contains an AWS Batch design in `infra/aws/hpc_compute.tf`, with separate model jobs and queues.

Therefore the repository is in a migration state with two orchestration concepts:

1. the documented monolithic EC2 path in `scripts/aws_orchestrator.py`; and
2. the emerging AWS Batch path used for the bounded canary.

Neither should be called the sole production implementation until the Batch path passes and the team explicitly chooses and documents the production control plane. The canary must not silently switch the scheduled orchestrator.

## Current canary scope

| Property | Value |
|---|---|
| Region | `alboran_1km` |
| Forecast window | 6 hours |
| Sequence | WRF, then CROCO and WW3 |
| Queue | Spot-only canary queue |
| WRF timeout | 90 minutes |
| CROCO timeout | 60 minutes |
| WW3 timeout | 60 minutes |
| Batch retries | 1 attempt |
| Maximum authorized total | USD 15.00 |
| EventBridge | must remain disabled |

Alboran was selected because the repository contains its WW3 `mod_def.ww3`; equivalent immutable WW3 model definitions are missing for the other four regions.

## Intended forcing model

The north-star AWS pipeline does **not** include CMEMS. ECMWF supplies the atmospheric input used by WRF, and WRF supplies atmospheric forcing to CROCO and WW3.

CROCO does not require CMEMS. It requires an initial model state, while external ocean boundary fields are needed only where the selected regional configuration has open boundaries. Depending on the experiment, CROCO can use an existing initial file, a restart, climatology, analytical initialization, or fields prepared from an external ocean product. A closed-boundary or idealized configuration has a different contract from an operational open-boundary forecast.

The [official CROCO interannual tutorial](https://data-croco.ifremer.fr/DOC/PRES_TRAINING_CROCO_2022_Cape_Town/BASICS/04_Basics-Thursday/TP_interanual_Captown_v1.pdf) demonstrates one choice: initial and boundary files prepared from Mercator/GLORYS, ECMWF atmospheric forcing, and subsequent months initialized from restart files. It presents CMEMS access as relevant to some datasets, not as a CROCO runtime requirement.

The current implementation in `scripts/run_marine_simulation.py` nevertheless hard-codes a CMEMS acquisition path. The code therefore does not yet match the intended architecture. The Alboran canary must explicitly choose and validate its CROCO initialization and boundary configuration instead of assuming that CMEMS must be replaced one-for-one.

Accordingly, CMEMS data fetched during earlier canary preparation is not a north-star dependency and should not be used as evidence that the desired no-CMEMS pipeline is complete.

## Inputs staged for the canary

- ECMWF Open Data for the selected cycle and steps 0, 3, and 6 hours, repacked and validated for WPS;
- the promoted immutable Alboran CROCO `v1.0` grid;
- Alboran WW3 `mod_def.ww3` and `ST4TABUHF2.bin`;
- a low-resolution WPS geographical dataset staged for technical testing.

The staged WPS geography is suitable only for exercising the pipeline. A low-resolution dataset was aliased to the path expected by the current WRF configuration after the historical high-resolution source became unavailable. This prevents any claim that the resulting atmosphere forecast is scientifically acceptable.

## Image-build status and expected finding

The first WRF image build exposed an incorrect compile command ordering. After correcting it, the compiler was killed by memory pressure in the 15 GiB CodeBuild environment. The later undefined linker symbols were secondary effects of that killed compilation.

The active hypothesis is:

> A one-run 72 GiB CodeBuild environment will complete WRF compilation, after which the same build will produce and push WRF, CROCO, and WW3 images.

Expected evidence is three non-null ECR digests plus a successful CodeBuild terminal state. If compilation still fails, the Batch canary must not be submitted. The next step would be to make the WRF build reproducible in a purpose-sized builder or publish a reviewed base image, rather than repeatedly spending on blind retries.

## Runtime contracts

### WRF

WRF receives run date, run ID, six-hour horizon, S3 bucket, ECMWF forcing, and WPS geography. It must publish exactly seven hourly `wrfout_d02` files (initial hour through hour six), logs, and `WRF_SUCCESS` beneath the run-scoped S3 prefix.

### CROCO

CROCO is intended to receive an explicit region, horizon, the region's compiled
MPI rank count (8 for Alboran), immutable `v1.0` grid, run-scoped WRF output,
and the initial/boundary inputs required by the selected CROCO configuration.
The existing runner still requires CMEMS even though CROCO itself does not.
The AWS runner must be refactored and tested against the chosen Alboran
configuration before it is represented as no-CMEMS-ready.

Each regional decomposition is a scientific/build constraint and must not be
changed without rebuilding and validating that regional binary.

### WW3

WW3 receives `alboran_1km`, the six-hour horizon, 24 MPI ranks, the run-scoped WRF output, and immutable WW3 static data. It derives regional wind forcing, runs WW3 preprocessing and simulation, and must publish a readable forecast NetCDF file, logs, and `WW3_SUCCESS`.

## What we expect to learn

The canary is designed to answer these questions:

1. Can each reviewed container start on AWS Batch with the intended runtime arguments and IAM permissions?
2. Does WRF consume the staged ECMWF and geography data and produce the exact hourly contract?
3. Can CROCO locate the canonical `v1.0` grid and WRF output, and does the selected Alboran configuration have a complete initial-state and boundary contract without CMEMS?
4. Can WW3 derive winds from WRF and run with the Alboran static grid?
5. Are S3 paths, markers, logs, timeouts, and dependency boundaries sufficient for reliable orchestration?
6. Does all paid model compute return to zero under success and failure?

It does not answer whether forecasts meet operational accuracy requirements.

## Success criteria

### Code correctness

- runner argument parsing and input validation pass tests;
- job definitions carry the required date, run ID, region, horizon, S3, and MPI values;
- images are addressable by immutable ECR digest;
- no unintended Terraform or canonical-grid change is required.

### Pipeline correctness

- CodeBuild succeeds and all three image digests exist;
- WRF succeeds before CROCO and WW3 are submitted;
- all jobs run only on the Spot-only canary queue;
- each job finishes within its hard timeout and produces its success marker;
- output NetCDF files open successfully and contain the required structural variables and time coverage;
- CloudWatch logs contain no unhandled error or truncated terminal failure;
- both Batch compute environments end with `desired_vcpus = 0`;
- EventBridge remains `DISABLED`;
- measured total AWS cost remains below USD 15.00.

### Scientific correctness

Not established by this canary. Scientific success requires approved reference datasets, metrics, tolerances, spin-up rules, conservation checks, and domain-specific review. None should be invented from infrastructure results.

## Failure criteria and stop conditions

Stop the sequence and do not submit downstream work if:

- any required ECR image or immutable input is absent;
- CodeBuild fails or produces an unverified image;
- WRF fails, times out, or publishes incomplete hourly output;
- a job resolves to the normal queue or On-Demand capacity;
- forecast hours, region, grid version, or MPI ranks differ from the approved values;
- projected or observed spend would exceed USD 15.00;
- EventBridge is enabled unexpectedly;
- output validation fails even when the process exits zero.

Do not repeatedly retry paid work without a new, evidence-based hypothesis.

## Cost and cleanup controls

The cost envelope assumes one `c6i.32xlarge` Spot worker at a time, hard job timeouts, one attempt, and no On-Demand fallback. Build cost, storage, transfer, and logs count against the same USD 15.00 ceiling.

Cleanup is complete only when:

- no canary job is `RUNNABLE`, `STARTING`, or `RUNNING`;
- Batch reports `desired_vcpus = 0` for Spot and On-Demand environments;
- no orphan worker instance remains;
- EventBridge remains disabled;
- run-scoped outputs and logs are retained for diagnosis; and
- canonical static data has not been deleted or overwritten.

## Missing before production

1. A successful, reproducible WRF/CROCO/WW3 image build and immutable image promotion policy.
2. A completed six-hour Alboran Batch canary with retained evidence.
3. WW3 `mod_def.ww3` artifacts for Algerian, Balearic, Gulf of Lion, and Tyrrhenian.
4. A defined and approved CROCO initialization strategy, plus boundary inputs only for boundaries configured as open.
5. Removal of the hard-coded CMEMS acquisition contract from the AWS CROCO runner after the selected configuration is implemented and tested.
6. Production-quality WPS geographical data from an available, versioned source.
7. Tests for runner contracts, Batch arguments, dependency submission, S3 markers, and failure cleanup.
8. A deliberate decision between the monolithic EC2 orchestrator and the Batch control plane.
9. Terraform reconciliation: some Batch files and changes are currently uncommitted, and the local environment used during preparation did not have Terraform available for validation.
10. Digest-pinned job definitions instead of mutable `latest` tags.
11. Cost telemetry that attributes build and model spend to one run ID.
12. Approved scientific acceptance criteria and an independent validation campaign.
13. IAM hardening and deployment from a non-root operational identity.
14. Multiple successful bounded runs before any schedule is enabled.

## Promotion path after the canary

If the canary passes:

1. preserve its manifests, image digests, logs, timings, outputs, and cost record;
2. review and commit the Batch infrastructure and runner changes;
3. validate and plan Terraform in CI before applying it;
4. repeat the test with production WPS geography;
5. add one region at a time as its immutable WW3 grid becomes available;
6. run a 72-hour manual rehearsal under a separately approved budget;
7. complete scientific validation;
8. enable scheduling only through an explicit production change review.

Passing a canary authorizes none of these steps automatically.

## Operational evidence checklist

For every canary or production run, retain:

- run ID, region, cycle, start/end timestamps, and forecast horizon;
- ECR image digests and job-definition revisions;
- exact S3 input and output URIs;
- CROCO grid version and WW3 grid identity;
- MPI ranks and resource requests;
- Batch job IDs, queue, attempts, status reasons, and durations;
- CloudWatch log stream names;
- structural output validation results;
- compute scale-down evidence and scheduler state;
- estimated and final attributed cost; and
- an explicit statement of what was not scientifically validated.
