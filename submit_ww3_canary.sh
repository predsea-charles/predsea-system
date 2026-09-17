#!/usr/bin/env bash
# submit_ww3_canary.sh — submit a short WW3 canary run at a given region
# and rank count, against the existing predsea-ww3-hpc job definition.
#
# Mirrors submit_canary.sh's safety pattern from the CROCO sweep:
#   - refuses forecast_hours > 3
#   - requires WRF forcing to already be staged at this run_id's expected
#     path (via stage_wrf_for_canary.sh) before submitting
#   - requires explicit typed confirmation before submitting
#
# IMPORTANT — unlike the CROCO version, this script does NOT assume 192 is
# the only valid mpi_ranks value. Whether WW3's rank count is genuinely a
# free runtime parameter or has its own constraints is exactly what Phase 0
# of README.md is for. Confirm before assuming --mpi-ranks 192 (or any
# other value) is actually valid for the region you're testing.

set -euo pipefail

REGION_AWS="eu-west-1"
JOB_QUEUE="predsea-models-canary"
JOB_DEFINITION="predsea-ww3-hpc"
FORECAST_HOURS="3"
RUN_DATE=$(date -u +%Y-%m-%d)
WW3_REGION=""
MPI_RANKS=""
RUN_ID_PREFIX=""
S3_BUCKET=""
JOB_NAME_SUFFIX=""

usage() {
  cat <<EOF
Usage: $0 --region <ww3_region_name> --mpi-ranks <n> --run-id-prefix <str> --s3-bucket <bucket> [options]

REQUIRED FIRST STEP: run stage_wrf_for_canary.sh to populate this run_id's
WRF forcing path. This script checks that path is non-empty and refuses to
submit if it isn't.

Required:
  --region <name>           WW3 region config name (must exist as both a
                             config WW3 can actually read AND have a
                             corresponding Batch job definition path — see
                             README.md Phase 0/1 before assuming this is
                             just a string swap).
  --mpi-ranks <n>            Rank count to request. Do not assume 192 is
                             valid without confirming WW3's actual rank
                             constraints in Phase 0.
  --run-id-prefix <str>     Distinct label for this canary's output path.
                             Must match the --canary-run-id used with
                             stage_wrf_for_canary.sh.
  --s3-bucket <bucket>      Output bucket (used to verify WRF staging
                             happened before submitting).

Optional:
  --forecast-hours <n>       Default: 3. Capped at 3.
  --run-date <YYYY-MM-DD>    Default: today (UTC)
  --job-name-suffix <str>    Extra label for the Batch job name
  --job-queue <name>         Default: predsea-models-canary
  --region-aws <aws-region>  Default: eu-west-1
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) WW3_REGION="$2"; shift 2 ;;
    --mpi-ranks) MPI_RANKS="$2"; shift 2 ;;
    --run-id-prefix) RUN_ID_PREFIX="$2"; shift 2 ;;
    --s3-bucket) S3_BUCKET="$2"; shift 2 ;;
    --forecast-hours) FORECAST_HOURS="$2"; shift 2 ;;
    --run-date) RUN_DATE="$2"; shift 2 ;;
    --job-name-suffix) JOB_NAME_SUFFIX="$2"; shift 2 ;;
    --job-queue) JOB_QUEUE="$2"; shift 2 ;;
    --region-aws) REGION_AWS="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

if [[ -z "$WW3_REGION" || -z "$MPI_RANKS" || -z "$RUN_ID_PREFIX" || -z "$S3_BUCKET" ]]; then
  echo "ERROR: --region, --mpi-ranks, --run-id-prefix, and --s3-bucket are all required."
  usage
fi

if (( FORECAST_HOURS > 3 )); then
  echo "ERROR: --forecast-hours=$FORECAST_HOURS exceeds the canary safety cap of 3."
  exit 1
fi

RUN_ID="${RUN_DATE}T0000Z-${RUN_ID_PREFIX}${JOB_NAME_SUFFIX:+-$JOB_NAME_SUFFIX}"

WRF_CHECK_PATH="s3://${S3_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/wrf/"
echo "Checking WRF forcing exists at: $WRF_CHECK_PATH"
WRF_OBJECT_COUNT=$(aws s3 ls "$WRF_CHECK_PATH" --recursive --region "$REGION_AWS" 2>/dev/null | wc -l | tr -d ' ')
if [[ "$WRF_OBJECT_COUNT" == "0" ]]; then
  echo "ERROR: no WRF output found at $WRF_CHECK_PATH"
  echo "Run stage_wrf_for_canary.sh FIRST with --canary-run-id matching this"
  echo "run's run_id ($RUN_ID), then re-run this script."
  exit 1
fi
echo "Found $WRF_OBJECT_COUNT WRF object(s) staged. Proceeding."

echo "----------------------------------------------------------------------"
echo "Submitting WW3 canary job"
echo "  region:          $WW3_REGION"
echo "  mpi_ranks:       $MPI_RANKS"
echo "  forecast_hours:  $FORECAST_HOURS"
echo "  run_date:        $RUN_DATE"
echo "  resolved run_id: $RUN_ID"
echo "  job_queue:       $JOB_QUEUE"
echo "  job_definition:  $JOB_DEFINITION"
echo "----------------------------------------------------------------------"
echo "REMINDER: confirm this region config and rank count were validated in"
echo "Phase 0/1 (README.md) before proceeding — this is a canary TEST of an"
echo "unproven configuration, not a known-good submission."
echo "----------------------------------------------------------------------"
read -r -p "Confirm you want to submit this canary (type 'yes'): " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "Aborted — no job submitted."
  exit 1
fi

JOB_NAME="ww3-canary-${RUN_ID_PREFIX}${JOB_NAME_SUFFIX:+-$JOB_NAME_SUFFIX}"

JOB_ID=$(aws batch submit-job \
  --job-name "$JOB_NAME" \
  --job-queue "$JOB_QUEUE" \
  --job-definition "$JOB_DEFINITION" \
  --parameters region="$WW3_REGION",forecast_hours="$FORECAST_HOURS",mpi_ranks="$MPI_RANKS",run_date="$RUN_DATE",run_id="$RUN_ID" \
  --region "$REGION_AWS" --query 'jobId' --output text)

echo "Submitted. Job ID: $JOB_ID"
echo ""
echo "Track status with:"
echo "  aws batch describe-jobs --jobs $JOB_ID --region $REGION_AWS --query 'jobs[].{name:jobName,status:status,logStreamName:container.logStreamName}' --output table"
echo ""
echo "Once RUNNING, get its log stream and measure with measure_rate.py —"
echo "but confirm the log format first (README.md Phase 0) before trusting"
echo "the parsed output."
