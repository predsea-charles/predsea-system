#!/usr/bin/env bash
set -euo pipefail

FORECAST_HOURS="${1:-72}"
MAX_AUTHORIZED_COST_USD="15.00"
RUN_DATE=$(date -u +%Y-%m-%d)
RUN_ID="${RUN_DATE}T0000Z-${FORECAST_HOURS}h"
REGION_AWS="eu-west-1"

echo "Forecast Hours: $FORECAST_HOURS | run_date: $RUN_DATE | run_id: $RUN_ID"
echo "Maximum authorized cost: USD $MAX_AUTHORIZED_COST_USD"
echo "Execution Profile: ECMWF -> WRF -> WW3"
echo "----------------------------------------------------------------------------------"

# 1. Submit ECMWF
ECMWF_JOB_ID=$(aws batch submit-job \
  --job-name "ecmwf-${FORECAST_HOURS}h" \
  --job-queue predsea-models-canary \
  --job-definition predsea-ecmwf-hpc \
  --parameters run_date="$RUN_DATE",lead_hours="$FORECAST_HOURS" \
  --region "$REGION_AWS" --query 'jobId' --output text)
echo "ECMWF job: $ECMWF_JOB_ID"

# 2. Submit WRF (Depends on ECMWF)
WRF_JOB_ID=$(aws batch submit-job \
  --job-name "wrf-${FORECAST_HOURS}h" \
  --job-queue predsea-models-canary \
  --job-definition predsea-wrf-hpc \
  --parameters run_date="$RUN_DATE",run_id="$RUN_ID",forecast_hours="$FORECAST_HOURS" \
  --depends-on jobId="$ECMWF_JOB_ID" \
  --region "$REGION_AWS" --query 'jobId' --output text)
echo "WRF job:   $WRF_JOB_ID (depends on ECMWF)"

ALL_JOB_IDS=("$ECMWF_JOB_ID" "$WRF_JOB_ID")

# 3. Submit WW3 (Depends on WRF)
WW3_JOB_ID=$(aws batch submit-job \
  --job-name "ww3-${FORECAST_HOURS}h" \
  --job-queue predsea-models-canary \
  --job-definition predsea-ww3-hpc \
  --parameters region="alboran_1km",forecast_hours="$FORECAST_HOURS",mpi_ranks=64,run_date="$RUN_DATE",run_id="$RUN_ID" \
  --depends-on jobId="$WRF_JOB_ID" \
  --region "$REGION_AWS" --query 'jobId' --output text)
echo "WW3 job:   $WW3_JOB_ID (depends on WRF)"
ALL_JOB_IDS+=("$WW3_JOB_ID")

echo "All 3 jobs successfully submitted."
echo "Execution sequence:"
echo "  1. ECMWF runs"
echo "  2. WRF runs"
echo "  3. WW3 runs"
echo ""
echo "To check status anytime, run:"
echo "aws batch describe-jobs --jobs ${ALL_JOB_IDS[*]} --region $REGION_AWS --query 'jobs[].{name:jobName,status:status}' --output table"
