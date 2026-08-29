#!/usr/bin/env bash
set -euo pipefail

REGION="alboran_1km"
FORECAST_HOURS="${1:-24}"
MPI_RANKS="16"
MAX_AUTHORIZED_COST_USD="15.00"
RUN_DATE=$(date -u +%Y-%m-%d)
RUN_ID="${RUN_DATE}T0000Z-${FORECAST_HOURS}h"

echo "Region: $REGION | Forecast hours: $FORECAST_HOURS | run_date: $RUN_DATE | run_id: $RUN_ID"
echo "Maximum authorized cost: USD $MAX_AUTHORIZED_COST_USD"
echo "Hypothesis: the prior failure was solely the missing ECMWF image manifest."
echo "Success: all four jobs succeed and publish their required S3 artifacts."
echo "Failure: any job fails/times out or the Spot-only queue/one-attempt contract changes."
echo "Cleanup: retain diagnostics; require Batch desired vCPUs to return to zero."

ECMWF_JOB_ID=$(aws batch submit-job \
  --job-name "ecmwf-${FORECAST_HOURS}h" \
  --job-queue predsea-models-canary \
  --job-definition predsea-ecmwf-hpc \
  --parameters run_date=$RUN_DATE,lead_hours=$FORECAST_HOURS \
  --region eu-west-1 --query 'jobId' --output text)
echo "ECMWF job: $ECMWF_JOB_ID"

WRF_JOB_ID=$(aws batch submit-job \
  --job-name "wrf-${FORECAST_HOURS}h" \
  --job-queue predsea-models-canary \
  --job-definition predsea-wrf-hpc \
  --parameters run_date=$RUN_DATE,run_id=$RUN_ID,forecast_hours=$FORECAST_HOURS \
  --depends-on jobId=$ECMWF_JOB_ID,type=SEQUENTIAL \
  --region eu-west-1 --query 'jobId' --output text)
echo "WRF job: $WRF_JOB_ID (depends on ECMWF)"

CROCO_JOB_ID=$(aws batch submit-job \
  --job-name "croco-${FORECAST_HOURS}h" \
  --job-queue predsea-models-canary \
  --job-definition predsea-croco_alboran_1km-hpc \
  --parameters region=$REGION,forecast_hours=$FORECAST_HOURS,mpi_ranks=$MPI_RANKS,run_date=$RUN_DATE,run_id=$RUN_ID \
  --depends-on jobId=$WRF_JOB_ID,type=SEQUENTIAL \
  --region eu-west-1 --query 'jobId' --output text)
echo "CROCO job: $CROCO_JOB_ID (depends on WRF)"

WW3_JOB_ID=$(aws batch submit-job \
  --job-name "ww3-${FORECAST_HOURS}h" \
  --job-queue predsea-models-canary \
  --job-definition predsea-ww3-hpc \
  --parameters region=$REGION,forecast_hours=$FORECAST_HOURS,run_date=$RUN_DATE,run_id=$RUN_ID \
  --depends-on jobId=$WRF_JOB_ID,type=SEQUENTIAL \
  --region eu-west-1 --query 'jobId' --output text)
echo "WW3 job: $WW3_JOB_ID (depends on WRF)"

echo ""
echo "All jobs submitted. Batch will run them in order automatically — this terminal doesn't need to stay open."
echo "To check status anytime: aws batch describe-jobs --jobs $ECMWF_JOB_ID $WRF_JOB_ID $CROCO_JOB_ID $WW3_JOB_ID --region eu-west-1 --query 'jobs[].{name:jobName,status:status}' --output table"
