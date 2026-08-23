#!/bin/bash
set -u

GCS_OUTPUT_BASE="gs://predsea-daily-outputs-test/predictions/2026-08-05/runs/ww3-24h-forecast"
REGIONS=("alboran_1km" "algerian_1km" "balearic_1km" "gulf_of_lion_1km" "tyrrhenian_1km")

echo "========================================================================"
echo "📊 WW3 24h Regional Forecast Progress Tracker"
echo "Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "========================================================================"
printf "%-18s | %-50s\n" "REGION" "CURRENT STEP / STATUS"
echo "-------------------|----------------------------------------------------"

for region in "${REGIONS[@]}"; do
  log_path="${GCS_OUTPUT_BASE}/${region}-output/run_trace.log"
  # Fetch last step marker from GCS trace log
  last_step=$(gsutil cat "$log_path" 2>/dev/null | grep -E '\[STEP|\[COMPLETE' | tail -n 1)
  
  if [ -z "$last_step" ]; then
    status_str="⏳ Initializing / Queueing VM..."
  else
    status_str="$last_step"
  fi
  printf "%-18s | %-50s\n" "$region" "$status_str"
done

echo "========================================================================"
