# PredSea AWS ETL and Simulation Pipeline

Last updated: 2026-10-09  
AWS region: `eu-west-1`  
Repository: `/Users/charles.santana/PredSea/predsea-system`

## 1. Purpose

This document describes the AWS-native PredSea daily ETL and numerical simulation pipeline: infrastructure, atmospheric boundary ingestion, the 72-hour WRF → WW3 model chain, S3 publication, Athena evidence export, API consumption, resource allocation, failure handling, and operational commands.

CROCO is no longer part of the daily pipeline. It was removed after the migration to AWS Batch confirmed WW3 could run successfully without it. All CROCO-related infrastructure (job definitions, ECR repositories, IAM roles, Terraform resources) has been decommissioned.

## 2. Local Python environment

```bash
cd /Users/charles.santana/PredSea/predsea-system
python3 -m venv .venv-aws
source .venv-aws/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-aws.txt
```

Confirm the AWS SDK:

```bash
which python
python -c "import boto3; print(boto3.__version__)"
```

## 3. AWS architecture

Terraform under `infra/aws` provisions:

- An encrypted, versioned S3 data lake (`predsea-daily-outputs`).
- ECR repositories for `api`, `orchestrator`, `wrf`, and `ww3`.
- An App Runner FastAPI service.
- An ECS Fargate daily orchestrator task.
- AWS Batch compute environments and job queues for HPC model jobs.
- EventBridge Scheduler (remains disabled until full validation passes).
- An Athena workgroup and Glue Data Catalog tables.
- AWS Secrets Manager secret containers.
- CodeBuild for remote container image builds.
- CloudWatch log groups.

### Batch compute environments and queues

Numerical model jobs (WRF and WW3) run on AWS Batch using Spot instances, not a long-lived EC2 instance. The active queue is:

```
predsea-models-canary   — Spot instances, used for all production runs
predsea-models          — additional queue (currently empty)
predsea-models-on-demand-temp — on-demand fallback (use sparingly; higher cost)
```

All three point to the `eu-west-1` compute environment. Instance types and
vCPU limits are configured in Terraform under `infra/aws`.

## 4. Daily control flow

The EventBridge schedule invokes the ECS Fargate task defined in `scripts/aws_daily_orchestrator.py`.

```text
EventBridge Scheduler
  → ECS Fargate orchestrator
    → Load Secrets Manager values
    → Download ECMWF Open Data forcing
    → Archive forcing to S3
    → Submit WRF Batch job (predsea-models-canary)
        → WPS + WRF 72-hour forecast
        → prepare_ww3_wind_from_wrf.py (runs in WRF container while wrfout files are local)
        → Upload wrfout + WRF_SUCCESS + wind forcing to S3
    → Submit WW3 Batch job (predsea-models-canary, depends on WRF)
        → Download mod_def.ww3 (grid, ~MB)
        → Download wind.nc + namelists from forcing/ww3/ prefix (~MB)
        → ww3_prnc → ww3_shel (MPI) → ww3_ounf
        → Upload WW3 output + WW3_SUCCESS to S3
    → Generate route briefings and evidence
    → Export validation evidence to Parquet
    → Serve results through FastAPI / Athena
```

Any job failure stops the chain. The orchestrator tracks job status by polling AWS Batch.

## 5. Secrets

The Fargate task loads these values from AWS Secrets Manager:

```
predsea/AEMET_API_KEY
predsea/SOCIB_API_KEY
predsea/COPERNICUS_USERNAME
predsea/COPERNICUS_PASSWORD
```

Terraform creates the containers but does not store values in state.

```bash
aws secretsmanager put-secret-value \
  --region eu-west-1 \
  --secret-id predsea/COPERNICUS_USERNAME \
  --secret-string 'YOUR_USERNAME'
```

## 6. Atmospheric ETL: ECMWF Open Data

`scripts/fetch_ecmwf_forcing.py` downloads pressure-level and surface GRIB2 fields and uploads them to:

```
s3://predsea-daily-outputs/forcing/ecmwf/<run-date>/
  ecmwf_pl_<cycle>.grib2
  ecmwf_sfc_<cycle>.grib2
  forcing_metadata.json
```

The downloader falls back to a prior ECMWF cycle if the requested cycle is not yet published, re-packs unsupported CCSDS messages, and validates GRIB decodability, time coverage, and expected forecast steps. Production forecast horizon is 72 hours.

## 7. WRF stage

WRF runs as an AWS Batch job on the `predsea-models-canary` queue. The job definition is `predsea-wrf-hpc`.

Container: built from `simulation/Dockerfile`, pushed to ECR as `predsea-wrf:latest`.

Batch job resources:

```
vCPUs requested: 128
Memory:          per job definition
Instance type:   Spot (c6i or compatible, configured in compute environment)
```

The runner script is `scripts/aws_wrf_runner.py`. Its sequence:

1. Download ECMWF forcing from `s3://.../forcing/ecmwf/<run-date>/`.
2. Download WPS geography static data from `s3://.../static/wrf/WPS_GEOG/`.
3. Run WPS: `ungrib.exe` → `geogrid.exe` → `metgrid.exe` → `real.exe`.
4. Run `wrf.exe` (128 MPI ranks, hardware-thread binding).
5. Validate that all 73 expected `wrfout_d02_*` files exist.
6. Write `WRF_SUCCESS` and sync all output to:

```
s3://predsea-daily-outputs/predictions/<run-date>/runs/<run-id>/wrf/
```

7. **Run `prepare_ww3_wind_from_wrf.py`** while the wrfout files are still on local disk (see section 8).

WPS configuration:

```bash
mpirun -np 128 --use-hwthread-cpus --bind-to hwthread --map-by hwthread wrf.exe
```

## 8. WRF-to-WW3 wind forcing

`scripts/prepare_ww3_wind_from_wrf.py` runs **inside the WRF Batch job** immediately after WRF completes, while the `wrfout_d02_*` files are still on local disk. This is the key architectural decision that eliminates the WW3 spot-interruption problem (see section 12).

The script:

1. Reads all 73 hourly `wrfout_d02_*` NetCDF files.
2. Extracts `U10` and `V10` (10 m wind components).
3. Interpolates from the WRF Lambert-conformal grid onto a regular lat/lon grid covering the target WW3 domain using KDTree inverse-distance weighting.
4. Writes a CF-compliant `wind.nc`.
5. Writes `ww3_prnc.nml`, `ww3_shel.nml`, and `ww3_ounf.nml`.
6. Writes `forcing_manifest.json`.

Generated files are uploaded to:

```
s3://predsea-daily-outputs/forcing/ww3/<run-date>/<region-id>/
```

Active region: **`western_mediterranean_2km`** (Gibraltar → Messina, lon −6..14, lat 35..44.5)

Dependencies installed in the WRF container: `numpy`, `scipy`, `xarray` (pip-installed in `simulation/Dockerfile`).

Region profiles are bundled in the WRF image at `/app/simulation/marine/regions/`.

## 9. WW3 stage

WW3 runs as an AWS Batch job on the `predsea-models-canary` queue, after the WRF job completes. The job definition is `predsea-ww3-hpc`.

Container: built from `Dockerfile.ww3-aws`, pushed to ECR as `predsea-ww3:latest`.

The runner script is `scripts/aws_ww3_runner.py`. Its sequence:

1. Download `mod_def.ww3` and other immutable grid files from:

```
s3://predsea-daily-outputs/static/native-marine/<region>/ww3-grid/
```

2. Download pre-generated wind forcing (wind.nc + namelists, **~MB not ~68 GB**) from:

```
s3://predsea-daily-outputs/forcing/ww3/<run-date>/<region>/
```

3. Verify all required inputs: `mod_def.ww3`, `wind.nc`, `ww3_prnc.nml`, `ww3_shel.nml`, `ww3_ounf.nml`.
4. Run `ww3_prnc`.
5. Run `ww3_shel` (24 MPI ranks, hardware-thread support).
6. Run `ww3_ounf` to produce NetCDF output.
7. Write `WW3_SUCCESS` and upload all output to:

```
s3://predsea-daily-outputs/predictions/<run-date>/runs/<run-id>/<region>/
```

Current allocation:

```
MPI ranks: 24
Active region: western_mediterranean_2km
Normal runtime: ~176 minutes
```

Grid path:

```
s3://predsea-daily-outputs/static/native-marine/<region>/ww3-grid/
```

## 10. Why WRF generates wind forcing (not WW3)

Prior to October 2026, the WW3 job generated its own wind forcing by downloading all 73 `wrfout_d02_*` files (~958 MB each, ~68 GB total) from S3, then running `prepare_ww3_wind_from_wrf.py`. This made the WW3 job vulnerable to spot instance termination: a spot interruption during the long download killed the job before any wave computation could begin.

WW3 was spot-terminated four times in a single 24-hour window before the architecture was changed.

The fix moves wind forcing generation into the WRF job, where the wrfout files are already on local disk. The WW3 job's download of the resulting forcing files takes seconds. The spot-interruption window for WW3 is now limited to the ~3 hour wave simulation itself, not the ~1–2 hour data download that precedes it.

## 11. S3 layout

```
s3://predsea-daily-outputs/
  forcing/
    ecmwf/<run-date>/                         ECMWF GRIB2 inputs
    ww3/<run-date>/<region>/                  WW3 wind forcing (wind.nc + namelists)
  static/
    wrf/WPS_GEOG/                             WPS geography (immutable)
    native-marine/<region>/ww3-grid/          WW3 grid files incl. mod_def.ww3
  predictions/<run-date>/runs/<run-id>/
    wrf/                                      wrfout_d02_* + WRF_SUCCESS
    <region>/                                 WW3 NetCDF output + WW3_SUCCESS
  warehouse/evidence_rows/                    Parquet validation archive
  athena-results/                             Athena query outputs (30-day TTL)
  transient/logs/<run-date>/<run-id>/         EC2 / Batch logs (30-day TTL)
```

## 12. Container image builds

Images are built by CodeBuild (`buildspec.aws.yml`) and pushed to ECR on every commit to `main`.

| Image | Dockerfile | ECR name |
|---|---|---|
| WRF | `simulation/Dockerfile` | `predsea-wrf` |
| WW3 | `Dockerfile.ww3-aws` | `predsea-ww3` |
| Orchestrator | `Dockerfile.orchestrator` | `predsea-orchestrator` |
| API | `Dockerfile.aws` | `predsea-api` |

To trigger a rebuild manually:

```bash
aws codebuild start-build \
  --region eu-west-1 \
  --project-name predsea-build
```

## 13. Evidence, Parquet, and Athena

After simulation completion, the orchestrator runs the briefing and validation pipeline.

`scripts/export_validation_to_athena.py` normalizes validation JSONL files and writes Parquet to:

```
s3://predsea-daily-outputs/warehouse/evidence_rows/run_date=<date>/run_id=<run-id>/evidence.parquet
```

Athena uses the `predsea_validation.evidence_rows` Glue table. The API queries through Athena when `PREDSEA_STORAGE_BACKEND=s3`.

## 14. API publication

The App Runner service reads route evidence and binary artifacts from S3 using `S3EvidenceStore`.

Publication includes run-scoped evidence, `latest_run.json`, `publication_status.json`, presigned artifact URLs, and Athena-backed forecast and observation queries.

## 15. No-cost local verification

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
  scripts/aws_wrf_runner.py \
  scripts/aws_ww3_runner.py \
  scripts/prepare_ww3_wind_from_wrf.py
```

Dry run:

```bash
python scripts/aws_daily_orchestrator.py \
  --dry-run \
  --forecast-hours 72
```

Run tests:

```bash
PYTHONPATH=.:humanintheloop python -m pytest -q \
  tests/aws/test_aws_orchestrator.py \
  tests/aws/test_aws_storage_migration.py \
  tests/aws/test_s3_evidence_store.py
```

## 16. Infrastructure validation

```bash
aws sts get-caller-identity
terraform -chdir=infra/aws init
terraform -chdir=infra/aws validate
terraform -chdir=infra/aws plan -var="schedule_state=DISABLED"
```

## 17. Preflight S3 validation

Check that the WW3 grid is staged before running:

```bash
aws s3 ls \
  s3://predsea-daily-outputs/static/native-marine/western_mediterranean_2km/ww3-grid/
```

The listing must include `mod_def.ww3` and any other required static files.

## 18. Live-run monitoring

Check what is running in Batch:

```bash
# Running jobs
aws batch list-jobs \
  --region eu-west-1 \
  --job-queue predsea-models-canary \
  --job-status RUNNING

# Recent completions
aws batch list-jobs \
  --region eu-west-1 \
  --job-queue predsea-models-canary \
  --job-status SUCCEEDED

# Recent failures
aws batch list-jobs \
  --region eu-west-1 \
  --job-queue predsea-models-canary \
  --job-status FAILED
```

Check S3 for today's outputs:

```bash
aws s3 ls \
  s3://predsea-daily-outputs/predictions/$(date +%Y-%m-%d)/ \
  --recursive
```

Inspect job logs (CloudWatch log group `/aws/batch/job`):

```bash
aws logs describe-log-streams \
  --region eu-west-1 \
  --log-group-name /aws/batch/job \
  --order-by LastEventTime \
  --descending \
  --limit 10
```

Then tail a stream:

```bash
aws logs tail /aws/batch/job \
  --region eu-west-1 \
  --log-stream-name <stream-name> \
  --follow
```

## 19. Required success evidence

A complete daily run produces:

- `s3://.../predictions/<run-date>/runs/<run-id>/wrf/WRF_SUCCESS`
- `s3://.../predictions/<run-date>/runs/<run-id>/wrf/wrfout_d02_*` — 73 files
- `s3://.../forcing/ww3/<run-date>/western_mediterranean_2km/wind.nc`
- `s3://.../forcing/ww3/<run-date>/western_mediterranean_2km/ww3_prnc.nml`
- `s3://.../forcing/ww3/<run-date>/western_mediterranean_2km/ww3_shel.nml`
- `s3://.../forcing/ww3/<run-date>/western_mediterranean_2km/ww3_ounf.nml`
- `s3://.../predictions/<run-date>/runs/<run-id>/western_mediterranean_2km/ww3.*.nc` — wave forecast
- `s3://.../predictions/<run-date>/runs/<run-id>/western_mediterranean_2km/WW3_SUCCESS`

Check success markers:

```bash
DATE=$(date +%Y-%m-%d)
aws s3 ls s3://predsea-daily-outputs/predictions/$DATE/ --recursive \
  | grep -E "WRF_SUCCESS|WW3_SUCCESS"
```

## 20. Operational cautions

- **EventBridge must remain disabled** until a complete manual run succeeds end-to-end.
- WRF and WW3 jobs run on Spot instances. Spot termination is a known failure mode — the WW3 architecture change (section 10) dramatically reduces its impact on WW3, but WRF termination still fails the chain.
- Do not enable automatic resubmission without first measuring the cost of double-charging for WRF compute.
- Do not infer scientific validity from a process exit code alone. Verify timestamps, spatial coverage, finite-value percentage, physical ranges, and expected output counts.
- WW3 `mod_def.ww3` is region-specific and compiled from the exact grid bathymetry. Never swap it between regions or reuse one from a prior grid version.
- App Runner deployment requires a manual `start-deployment` call after CodeBuild pushes a new API image (auto-deploy from ECR is not currently wired up).
