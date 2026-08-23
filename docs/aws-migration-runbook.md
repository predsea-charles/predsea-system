# PredSea AWS migration runbook

## What is deployed

The AWS runtime is isolated from the legacy GCP runtime during migration. Terraform in `infra/aws` provisions the encrypted/versioned S3 data lake, five ECR repositories, App Runner API, ECS Fargate orchestrator task, EventBridge Scheduler, Athena/Glue catalog, Secrets Manager entries, CodeBuild, CloudWatch logs, and least-privilege runtime roles. The simulation worker is an ephemeral `c6i.32xlarge` Spot instance created by `scripts/aws_orchestrator.py`, with a 300 GB encrypted gp3 root disk configured for 3,000 IOPS and 500 MB/s.

The production simulation contract is fixed at 72 forecast hours. WRF uses 128 MPI ranks with hardware-thread pinning and a 16×8 domain decomposition. CROCO remains at 16 ranks because its regional binaries are compiled for fixed decompositions; WW3 uses 24 ranks per regional pass. Do not change those ranks merely to occupy all vCPUs—recompile and validate the model decomposition first.

The canonical CROCO grid rule remains unchanged during migration: never copy a candidate directly into a canonical grid prefix. `scripts/promote_croco_grid.py` remains the only promotion entry point. An S3 canonical promotion must not be introduced until that script performs the same region validation before constructing the S3 destination.

## Deployment

1. Confirm the AWS account and `eu-west-1` quota for at least one `c6i.2xlarge` Spot instance.
2. Choose a globally unique Terraform `output_bucket_name` if `predsea-daily-outputs` is unavailable. Set `croco_grid_version` to an immutable version that exists for all five regions.
3. Run `./deploy_aws.sh -var='croco_grid_version=<validated-version>'`. It applies Terraform, uploads a source archive, builds all images in CodeBuild, pushes ECR tags, and starts an App Runner deployment.
4. Put secret values into the created `predsea/*` secrets. Terraform intentionally creates secret containers but never stores secret values in state.
5. The schedule is created disabled. Manually run the Fargate task once, complete the gates below, then apply with `-var=schedule_state=ENABLED`.

## Verification gates

1. **Boundary downloads:** run the orchestrator task with a short horizon. Confirm non-empty ECMWF objects under `s3://<bucket>/forcing/ecmwf/<date>/`, CMEMS NetCDF under `forcing/cmems/<date>/`, encryption `AES256`, and expected time coverage.
2. **Spot execution:** confirm the instance has `CostCenter=PredSea`, type `c6i.2xlarge`, Spot lifecycle, IMDSv2 required, and the simulation instance profile. Watch `/predsea/orchestrator` and the run's `logs/ec2-user-data.log`.
3. **Termination safety:** confirm the instance reaches `terminated` after success and after an intentionally failing staging image. Confirm `SIMULATION_STATUS.json` says `SUCCESS` or `FAILED`. Test the orchestrator timeout with a bounded staging run and verify forced termination.
4. **S3 output:** validate the run prefix has model files, logs, and status. Open NetCDF outputs and check dimensions, time axis, finite-value coverage, physical ranges, and the exact requested run ID.
5. **Athena:** write a small Parquet evidence batch with `scripts.aws.warehouse.write_evidence_rows`, run `MSCK REPAIR TABLE predsea_validation.evidence_rows` if partitions are not projected, and query by `run_date`, provider, variable, and station.
6. **API:** call `/health`, routes, maps, place weather, and an artifact URL against App Runner. Confirm S3 evidence is used and presigned links expire. Compare representative responses with GCP before traffic cutover.
7. **Parallel run:** operate AWS and GCP for at least several daily cycles. Compare boundary checksums/metadata, model field statistics, route classifications, observation counts, anomaly results, and API response schemas.
8. **Cost guardrails:** create AWS Budgets alerts at 50%, 75%, and 90% of the remaining credit balance; monitor NAT, App Runner idle, Athena bytes scanned, EBS remnants, and Spot runtimes. Prefer S3/Athena and one minimum App Runner instance while validating.

Do not cut over DNS until all gates pass. Keep GCP artifacts read-only until retention and rollback requirements are agreed.
