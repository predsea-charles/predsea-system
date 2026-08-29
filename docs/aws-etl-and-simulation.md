# PredSea AWS ETL and Simulation Pipeline

Last updated: 2026-08-23  
AWS region: `eu-west-1`  
Repository: `/Users/charles.santana/PredSea/predsea-system`

## 1. Purpose

This document describes the AWS-native PredSea daily ETL and numerical simulation pipeline: infrastructure, atmospheric and ocean boundary ingestion, the 72-hour WRF → CROCO → WW3 model chain, S3 publication, Athena evidence export, API consumption, resource allocation, failure handling, and test commands.

The AWS path runs alongside the legacy GCP path during migration. AWS runtime selection is controlled with `PREDSEA_STORAGE_BACKEND=s3`; legacy rollback code remains available with `PREDSEA_STORAGE_BACKEND=gcs`.

## 2. Local Python environment

The system Python on a Mac does not necessarily include `boto3`. The error:

```text
ModuleNotFoundError: No module named 'boto3'
```

means the AWS Python dependencies have not been installed in the active interpreter.

Create an isolated environment rather than installing packages globally:

```bash
cd /Users/charles.santana/PredSea/predsea-system
python3 -m venv .venv-aws
source .venv-aws/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-aws.txt
```

Confirm the interpreter and AWS SDK:

```bash
which python
python -c "import boto3; print(boto3.__version__)"
```

For only the lightweight orchestrator dry run, the minimum install is:

```bash
python3 -m venv .venv-aws
source .venv-aws/bin/activate
python -m pip install boto3 botocore
```

The complete `requirements-aws.txt` environment is required for ETL, NetCDF, Parquet, API, and Athena work.

## 3. AWS architecture

Terraform under `infra/aws` provisions:

- An encrypted, versioned S3 data lake.
- ECR repositories for `api`, `orchestrator`, `wrf`, `croco`, and `ww3`.
- An App Runner FastAPI service.
- An ECS Fargate daily orchestrator task.
- EventBridge Scheduler, created disabled until manual validation passes.
- An Athena workgroup and Glue Data Catalog tables.
- AWS Secrets Manager secret containers.
- CodeBuild for remote container builds.
- CloudWatch log groups.
- An EC2 instance profile for the numerical worker.
- Separate task, execution, scheduler, simulation, App Runner, and CodeBuild IAM roles.

The numerical workload runs on one ephemeral EC2 Spot instance:

```text
Instance:       c6i.32xlarge
AWS vCPUs:      128
Physical cores: 64, with two hardware threads per core
Root disk:      300 GB gp3
IOPS:           3,000
Throughput:     500 MB/s
Encryption:     enabled
Interruption:   terminate
Metadata:       IMDSv2 required
```

The AWS account quota of 256 vCPUs permits two such instances, but the current pipeline launches only one.

## 4. Daily control flow

The EventBridge schedule invokes the ECS Fargate task defined in `scripts/aws_daily_orchestrator.py`.

The daily sequence is:

```text
EventBridge Scheduler
  → ECS Fargate orchestrator
    → Load Secrets Manager values
    → Download ECMWF Open Data
    → Download and validate native regional 3-D CMEMS forcing
    → Archive forcing to S3
    → Launch one c6i.32xlarge Spot instance
      → WRF 72-hour forecast
      → WRF-to-WW3 wind adapter
      → Five CROCO regional forecasts, sequentially
      → Five WW3 regional forecasts, sequentially
      → Upload outputs and logs
      → Auto-terminate EC2 instance
    → Generate route briefings and evidence
    → Export validation evidence to Parquet
    → Query through Athena and the FastAPI service
```

Any unhandled failure stops the chain because the EC2 User Data script uses `set -Eeuo pipefail`. The termination trap still attempts to upload diagnostics and terminate the instance.

## 5. Secrets

The Fargate task loads these values from AWS Secrets Manager:

```text
predsea/AEMET_API_KEY
predsea/SOCIB_API_KEY
predsea/COPERNICUS_USERNAME
predsea/COPERNICUS_PASSWORD
```

Terraform creates the secret containers but does not store values in Terraform state.

Example secret update:

```bash
aws secretsmanager put-secret-value \
  --region eu-west-1 \
  --secret-id predsea/COPERNICUS_USERNAME \
  --secret-string 'YOUR_USERNAME'
```

Repeat for each required secret. Avoid committing values or placing them in Terraform variables.

## 6. Atmospheric ETL: ECMWF Open Data

`scripts/fetch_ecmwf_forcing.py` uses the `ecmwf-opendata` Python package. It is the default atmospheric source.

The downloader:

1. Selects the requested model date and cycle.
2. Falls back to a prior available ECMWF cycle when the requested cycle is not published yet.
3. Downloads pressure-level and surface GRIB2 fields.
4. Re-packs unsupported CCSDS messages when necessary.
5. Normalizes soil metadata for WPS.
6. Validates GRIB decodability, time coverage, cycle metadata, and expected forecast steps.
7. Uploads the validated artifacts and a forcing manifest to S3.

S3 layout:

```text
s3://predsea-daily-outputs/forcing/ecmwf/<run-date>/
  ecmwf_pl_<cycle>.grib2
  ecmwf_sfc_<cycle>.grib2
  forcing_metadata.json
```

The production AWS forecast horizon is fixed at 72 hours.

## 7. Ocean ETL: Copernicus Marine

`scripts/fetch_native_marine_forcing.py` downloads CMEMS Mediterranean ocean data using the Copernicus credentials from Secrets Manager. The generic 2-D `scripts/fetch_cmems_forcing.py` is not part of the AWS daily pipeline because it does not satisfy CROCO's native 3-D forcing contract.

Before EC2 is launched, the orchestrator stages each of the five regions independently and validates exact hourly coverage plus the required `uo`, `vo`, `thetao`, `so`, `zos`, depth, and time fields. Region-scoped filenames prevent one domain from reusing another domain's bounding box.

S3 layout:

```text
s3://predsea-daily-outputs/forcing/cmems/<run-date>/
  <validated CMEMS NetCDF products>
```

The ETL must validate that files are non-empty and cover the requested 72-hour interval before launching expensive compute.

## 8. EC2 Spot orchestration

`scripts/aws_orchestrator.py` requests a one-time `c6i.32xlarge` Spot instance through `boto3`.

The launch request includes:

- The PredSea simulation instance profile.
- Encrypted 300 GB gp3 root storage.
- 3,000 provisioned IOPS.
- 500 MB/s provisioned throughput.
- Required IMDSv2 tokens.
- `CostCenter=PredSea` and run-ID tags.
- Spot interruption behavior set to terminate.
- User Data containing the complete model chain.

The orchestrator polls EC2 state, streams available console output, checks the S3 completion marker, enforces a 24-hour default timeout, and forcibly terminates a timed-out worker.

## 9. WRF stage

WRF runs first because both CROCO and WW3 depend on its atmospheric fields.

Current allocation:

```text
MPI ranks:       128
WRF layout:      16 × 8
Hardware threads: enabled
OpenMPI binding: hardware-thread binding and mapping
Forecast:        72 hours
```

The relevant MPI execution is effectively:

```bash
mpirun -np 128 \
  --use-hwthread-cpus \
  --bind-to hwthread \
  --map-by hwthread \
  wrf.exe
```

WPS runs before WRF:

1. Split ECMWF GRIB data by valid time.
2. Run `ungrib.exe`.
3. Verify every required intermediate timestamp.
4. Run `geogrid.exe`.
5. Run `metgrid.exe`.
6. Run `real.exe` with 128 ranks.
7. Run `wrf.exe` with 128 ranks.

Output is written locally under `/workspace/outputs/wrf` and uploaded to:

```text
s3://predsea-daily-outputs/predictions/<run-date>/runs/<run-id>/wrf/
```

## 10. WRF-to-WW3 adapter

After WRF completes, `scripts/prepare_ww3_wind_from_wrf.py`:

1. Reads hourly `wrfout_d02_*` files.
2. Extracts `U10`, `V10`, timestamps, latitude, and longitude.
3. Interpolates WRF winds onto each WW3 regional grid.
4. Writes `wind.nc`.
5. Writes `ww3_prnc.nml`, `ww3_shel.nml`, and `ww3_ounf.nml`.
6. Creates a forcing manifest for all five regions.

Generated forcing is uploaded to:

```text
s3://predsea-daily-outputs/forcing/ww3/<run-date>/<region-id>/
```

## 11. CROCO stage

CROCO runs after WRF-to-WW3 preprocessing.

Regions execute sequentially in this order:

1. `alboran_1km`
2. `algerian_1km`
3. `balearic_1km`
4. `gulf_of_lion_1km`
5. `tyrrhenian_1km`

Each CROCO binary has a fixed compile-time decomposition. The AWS Batch job
definition and runtime rank count must use the matching regional allocation:

| Region | Decomposition | MPI ranks / requested vCPUs |
| --- | ---: | ---: |
| `alboran_1km` | 4 × 2 | 8 |
| `algerian_1km` | 6 × 2 | 12 |
| `balearic_1km` | 4 × 4 | 16 |
| `gulf_of_lion_1km` | 2 × 2 | 4 |
| `tyrrhenian_1km` | 6 × 4 | 24 |

Regions run sequentially. Changing any rank count requires rebuilding and
validating that regional binary; a successful process exit alone is not
evidence of scientific validity.

Each CROCO run:

1. Downloads its immutable canonical grid from S3.
2. Calls `validate_grid_matches_region()` locally.
3. Verifies grid dimensions match the compiled regional binary.
4. Downloads WRF output from the same run ID.
5. Resolves the configured ocean-state provider. `alboran_1km` defaults to
   pre-staged CROCO files; legacy regions may explicitly select `cmems`.
6. Stages or builds the ocean files and builds WRF-derived bulk-atmosphere
   forcing.
7. Runs the regional CROCO executable with its compiled rank count from the
   table above.
8. Validates the resulting NetCDF fields.
9. Uploads the canonical forecast and `CROCO_SUCCESS` marker.

### Alboran CROCO runtime contract

The Batch image does not compile a distinct Alboran physics profile. All five
regional executables are compiled from the patched `BALEARIC_1KM` branch, with
region-specific grid dimensions and MPI decomposition. That active branch has
all four `OBC_*` sides, `CLIMATOLOGY`, `FRC_BRY` (including `Z_FRC_BRY`,
`M2_FRC_BRY`, `M3_FRC_BRY`, and `T_FRC_BRY`), and `BULK_FLUX` enabled.
`ANA_INITIAL` and `ANA_BRY` are not enabled.

Consequently, the current Alboran binary requires these staged ocean files:

```text
croco_ini.nc
croco_bry.nc
croco_clm.nc
```

WRF conversion generates `croco_blk.nc` and `croco_frc.nc`. The canonical
grid is staged as `croco_grid.nc`. Set `PREDSEA_CROCO_INPUTS_S3_URI` (or the
GCS equivalent) to a region-scoped prefix containing the three ocean files,
or mount them under `/workspace/inputs/croco/alboran_1km/`. CMEMS is available
only when explicitly selected with `--croco-ocean-source cmems` or
`PREDSEA_CROCO_OCEAN_SOURCE=cmems`; it is not acquired on the default Alboran
path.

This corrects the earlier description in sections 4 and 7: those sections
describe the legacy five-region CMEMS ETL, not the no-CMEMS Alboran canary.

Canonical grid path:

```text
s3://predsea-daily-outputs/static/native-marine/<region-id>/croco-grid/<version>/croco_grid.nc
```

Never copy a CROCO grid directly into this location. The only supported promotion pathway is:

```bash
python scripts/promote_croco_grid.py \
  --source <local-or-cloud-candidate> \
  --region <region-id> \
  --version <immutable-version> \
  --bucket predsea-daily-outputs \
  --destination-backend s3
```

## 12. WW3 stage

WW3 begins only after all five CROCO regions finish successfully.

Regions execute sequentially in the same order as CROCO.

Current allocation per region:

```text
MPI ranks: 24
Regions running concurrently: 1
Approximate active vCPUs: 24
```

Each WW3 run:

1. Downloads `mod_def.ww3` and other immutable grid files.
2. Downloads the WRF-derived `wind.nc` and WW3 namelists.
3. Runs `ww3_prnc`.
4. Runs `ww3_shel` on 24 MPI ranks with hardware-thread support.
5. Runs `ww3_ounf` to create NetCDF output.
6. Verifies that NetCDF output exists.
7. Uploads outputs and `WW3_SUCCESS`.

Grid path:

```text
s3://predsea-daily-outputs/static/native-marine/<region-id>/ww3-grid/
```

Output path:

```text
s3://predsea-daily-outputs/predictions/<run-date>/runs/<run-id>/<region-id>/
```

## 13. CPU utilization and the 256-vCPU quota

The quota is an account/region ceiling; it does not automatically parallelize the workload.

Current maximum simultaneous usage:

| Stage | MPI ranks | Approximate vCPUs used | Execution |
|---|---:|---:|---|
| WRF | 128 | 128 | One run |
| CROCO | 16 | 16 | Five regions sequentially |
| WW3 | 24 | 24 | Five regions sequentially |

Only one 128-vCPU instance is currently launched. Therefore:

- WRF uses the full instance.
- CROCO leaves roughly 112 vCPUs idle.
- WW3 leaves roughly 104 vCPUs idle.
- The second 128-vCPU quota allocation is unused.

This is intentional for the first correctness gate. After validation, regional CROCO jobs could run concurrently up to 80 ranks total, and regional WW3 jobs could run concurrently up to 120 ranks total. A two-instance design could use the full 256-vCPU quota, but it should be introduced only after measuring memory, disk I/O, S3 throughput, and Spot interruption behavior.

## 14. Completion and termination safety

The EC2 User Data script registers an exit trap before installing dependencies or running a model.

At boot, the instance also schedules an independent 26-hour operating-system shutdown. Because instance-initiated shutdown behavior is `terminate`, this is a hard maximum-age guard if the Fargate supervisor disappears.

On success or failure, it attempts to:

1. Write `SIMULATION_STATUS.json` with status, exit code, and instance ID.
2. Sync `/workspace/outputs` to the exact S3 run prefix.
3. Upload `/var/log/predsea-simulation.log` under `transient/logs/<run-date>/<run-id>/` (30-day retention).
4. Call `ec2:TerminateInstances` on itself.
5. Fall back to operating-system shutdown if the API call fails.

The top-level status remains `FAILED` until all WRF, CROCO, and WW3 stages complete.

## 15. Evidence, Parquet, and Athena

After simulation completion, the Fargate orchestrator runs the briefing and validation pipeline.

`scripts/export_validation_to_athena.py` reads:

```text
validation/observation_samples.jsonl
validation/forecast_index.jsonl
validation/station_metadata.jsonl
```

It normalizes them and writes Parquet to:

```text
s3://predsea-daily-outputs/warehouse/evidence_rows/run_date=<date>/run_id=<run-id>/evidence.parquet
```

Athena uses the `predsea_validation.evidence_rows` Glue table. The API uses Athena for prioritized forecast and observation queries when:

```bash
PREDSEA_STORAGE_BACKEND=s3
```

Athena query results are written under:

```text
s3://predsea-daily-outputs/athena-results/
```

The workgroup rejects queries above the configured 10 GiB scan cutoff. Current forcing objects, transient worker logs, and Athena results expire after 30 days; canonical forecast and validation outputs do not.

## 16. API publication

The App Runner service reads route evidence and binary artifacts from S3 using `S3EvidenceStore`.

Publication includes:

- Run-scoped evidence and briefing files.
- `latest_run.json`.
- `publication_status.json`.
- Presigned artifact URLs.
- Athena-backed forecast and observation queries.

The daily run publishes `STARTED`, `SUCCEEDED`, or `FAILED` status documents to the run prefix and latest-status path.

Each non-dry run also publishes and terminally updates:

```text
s3://<bucket>/predictions/<run-date>/runs/<run-id>/run_cost_ledger.json
```

The ledger keeps EC2 Spot, EBS, transfer, Fargate, and Athena costs visibly
pending until attributed billing data is available. S3 and CloudWatch amounts
are always labeled `provisional_estimate`; reviewed estimates may be supplied
with `PREDSEA_PROVISIONAL_S3_COST_USD` and
`PREDSEA_PROVISIONAL_CLOUDWATCH_COST_USD`. If either assumption is absent, its
amount is `null` and `pricing_status` is `unpriced`, rather than reporting a
misleading zero.

Before the EC2 request is submitted, the control plane validates the complete
CROCO region/rank plan against the compiled contract (8, 12, 16, 4, and 24
ranks in canonical region order). The validated plan is also used to render
the worker commands, so a mismatch fails before paid compute starts.

## 17. No-cost local verification

Activate the environment first:

```bash
cd /Users/charles.santana/PredSea/predsea-system
source .venv-aws/bin/activate
export AWS_REGION=eu-west-1
```

Compile Python:

```bash
python -m py_compile \
  scripts/aws_orchestrator.py \
  scripts/aws_daily_orchestrator.py \
  scripts/aws_ww3_runner.py \
  scripts/run_marine_simulation.py
```

Check shell syntax:

```bash
bash -n deploy_aws.sh simulation/run_pipeline.sh
```

Run the no-cost orchestration preview:

```bash
python scripts/aws_daily_orchestrator.py \
  --dry-run \
  --forecast-hours 72
```

Run focused tests:

```bash
PYTHONPATH=.:humanintheloop python -m pytest -q \
  tests/aws/test_aws_orchestrator.py \
  tests/aws/test_aws_storage_migration.py \
  tests/aws/test_s3_evidence_store.py
```

## 18. Infrastructure validation

```bash
aws sts get-caller-identity
terraform -chdir=infra/aws init
terraform -chdir=infra/aws validate
```

Set the immutable CROCO grid version:

```bash
export CROCO_GRID_VERSION="<validated-version>"
```

Plan without enabling the schedule:

```bash
terraform -chdir=infra/aws plan \
  -var="croco_grid_version=$CROCO_GRID_VERSION" \
  -var="schedule_state=DISABLED"
```

Deploy:

```bash
./deploy_aws.sh \
  -var="croco_grid_version=$CROCO_GRID_VERSION" \
  -var="schedule_state=DISABLED"
```

## 19. Preflight S3 validation

```bash
export PREDSEA_BUCKET=predsea-daily-outputs

for REGION in \
  alboran_1km \
  algerian_1km \
  balearic_1km \
  gulf_of_lion_1km \
  tyrrhenian_1km
do
  aws s3 ls \
    "s3://$PREDSEA_BUCKET/static/native-marine/$REGION/croco-grid/$CROCO_GRID_VERSION/croco_grid.nc"

  aws s3 ls \
    "s3://$PREDSEA_BUCKET/static/native-marine/$REGION/ww3-grid/mod_def.ww3"
done
```

All ten objects must exist before a paid run.

## 20. Live-run monitoring

Follow orchestration logs:

```bash
aws logs tail /predsea/orchestrator \
  --region eu-west-1 \
  --follow \
  --since 10m
```

Find the numerical worker:

```bash
aws ec2 describe-instances \
  --region eu-west-1 \
  --filters \
    Name=tag:CostCenter,Values=PredSea \
    Name=instance-state-name,Values=pending,running \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,LaunchTime]' \
  --output table
```

Inspect recent run outputs:

```bash
aws s3 ls \
  s3://predsea-daily-outputs/predictions/ \
  --recursive | tail -100
```

Required success evidence:

- WRF hourly outputs for the requested 72 hours.
- Five validated CROCO NetCDF outputs.
- Five `CROCO_SUCCESS` markers.
- Five WW3 NetCDF outputs.
- Five `WW3_SUCCESS` markers.
- `SIMULATION_STATUS.json` containing `SUCCESS`.
- Uploaded EC2 User Data log.
- Terminated Spot instance.
- Parquet evidence visible through Athena.

## 21. Current operational cautions

- EventBridge must remain disabled until a complete manual run succeeds.
- The current run is a full 72-hour forecast; there is no paid short-horizon canary in the production AWS orchestrator.
- A Spot interruption fails the current EC2 model chain; automatic whole-chain resubmission has not yet been added to the AWS orchestrator.
- All five CROCO grids must share the configured immutable version segment.
- WW3 requires a valid `mod_def.ww3` for every region.
- Do not infer that a process exit code alone proves scientific validity. Verify timestamps, spatial coverage, finite-value percentage, physical ranges, and expected output counts.
- Do not enable two 128-vCPU workers merely because the quota exists. First validate one-worker correctness and measure actual runtime, memory, and I/O.
