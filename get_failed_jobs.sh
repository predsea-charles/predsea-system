#!/usr/bin/env bash
#
# get_specific_failed_logs.sh
# Retrieves diagnostic logs for the 4 specific failed jobs from the 15:03 batch.

PROJECT_ID="predsea-api"
LOCATION="europe-west1"
LOG_LIMIT=20

# Exact list of failed jobs from your query
FAILED_JOBS=(
  "predsea-sim-gulf-of-lion-1km-croco-b21ee2f5"
  "predsea-sim-algerian-1km-croco-1896bab7"
  "predsea-sim-alboran-1km-croco-266039f8"
  "predsea-sim-tyrrhenian-1km-croco-e3427b33"
)

echo "================================================================="
echo " Fetching logs for specific failed CROCO jobs"
echo "================================================================="

for JOB_ID in "${FAILED_JOBS[@]}"; do
  echo ""
  echo "-----------------------------------------------------------------"
  echo "🚨 JOB FAILED: ${JOB_ID}"
  echo "-----------------------------------------------------------------"

  # Fetch High-Level Exit Status
  echo ">>> STATUS REASON:"
  gcloud batch jobs describe "${JOB_ID}" \
    --location="${LOCATION}" \
    --project="${PROJECT_ID}" \
    --format="value(status.statusEvents[-1].description)"

  echo ""
  echo ">>> LAST ${LOG_LIMIT} LOG LINES FROM CLOUD LOGGING:"
  
  # Read execution logs filtered by job ID
  gcloud logging read "${JOB_ID}" \
    --project="${PROJECT_ID}" \
    --limit=${LOG_LIMIT} \
    --order="desc" \
    --format="value(textPayload, jsonPayload.message)"
    
  echo "-----------------------------------------------------------------"
done

echo ""
echo "Finished fetching target logs."
