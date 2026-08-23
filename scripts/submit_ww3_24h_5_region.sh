#!/bin/bash
set -euo pipefail

# PredSea WW3 24h Forecast 5-Region Submission Script
# (docs/agent-handoff-ww3-wrf-migration-2026-08-05.md §8.5 - §8.6)
#
# Core allocation uses the proven proportional split based on active sea-point count:
#   tyrrhenian_1km  : 24 vCPU (n2-custom-24-24576)
#   balearic_1km    : 16 vCPU (n2-highcpu-16)
#   algerian_1km    : 12 vCPU (n2-custom-12-12288)
#   alboran_1km     :  8 vCPU (n2-highcpu-8)
#   gulf_of_lion_1km:  4 vCPU (n2-highcpu-4)
# Total: 64 vCPU (exact project quota ceiling, all 5 run concurrently in parallel)

GCS_FORCING_BASE="gs://predsea-daily-outputs-test/scratch/ww3-24h-test"
GCS_GRID_BASE="gs://predsea-daily-outputs-test/scratch/ww3-smoke-test"
GCS_OUTPUT_BASE="gs://predsea-daily-outputs-test/predictions/2026-08-05/runs/ww3-24h-forecast"

REGION_SPECS="tyrrhenian_1km:24:n2-custom-24-24576 balearic_1km:16:n2-highcpu-16 algerian_1km:12:n2-custom-12-12288 alboran_1km:8:n2-highcpu-8 gulf_of_lion_1km:4:n2-highcpu-4"

TIMESTAMP="$(date +%s)"

for entry in $REGION_SPECS; do
  region="${entry%%:*}"
  rest="${entry#*:}"
  cores="${rest%%:*}"
  machine="${rest#*:}"
  cpu_milli=$((cores * 1000))
  memory_mib=$((cores * 1024))

  job_id_safe="ww3-24h-${region//_/-}-${TIMESTAMP}"
  echo "=== Submitting 24h WW3 forecast for region '$region' ($cores vCPU, $machine) ==="

  cat > "/tmp/${job_id_safe}.json" << EOF
{
  "taskGroups": [
    {
      "taskSpec": {
        "runnables": [
          {
            "container": {
              "imageUri": "europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/ww3-batch:latest",
              "entrypoint": "/bin/bash",
              "options": "--shm-size=8g",
              "commands": [
                "-c",
                "exec > >(tee -a run_trace.log) 2>&1; set -ex; mkdir -p /workspace/ww3 && cd /workspace/ww3; ( while true; do sleep 15; gsutil -q cp run_trace.log ${GCS_OUTPUT_BASE}/$region-output/run_trace.log >/dev/null 2>&1 || true; done ) & LOGGER_PID=\$!; echo '[STEP 1/5] Downloading grid model files...'; gsutil cp ${GCS_GRID_BASE}/$region/mod_def.ww3 . ; echo '[STEP 2/5] Downloading wind forcing files...'; gsutil cp ${GCS_FORCING_BASE}/$region/wind.nc . && gsutil cp ${GCS_FORCING_BASE}/$region/ww3_prnc.nml . && gsutil cp ${GCS_FORCING_BASE}/$region/ww3_shel.nml . ; echo '[STEP 3/5] Preprocessing wind forcing via ww3_prnc...'; ww3_prnc ; echo '[STEP 4/5] Executing Wavewatch III forecast solver (ww3_shel) on $cores cores...'; mpirun --allow-run-as-root --use-hwthread-cpus -np $cores ww3_shel ; echo '[STEP 5/5] Uploading forecast outputs to GCS...'; echo 'status=SUCCESS' > FORECAST_RESULT.txt ; kill \$LOGGER_PID 2>/dev/null || true; gsutil cp -r /workspace/ww3 ${GCS_OUTPUT_BASE}/$region-output ; echo '[COMPLETE] 24h Forecast completed successfully!'"
              ]
            },
            "environment": {
              "variables": {
                "OMPI_ALLOW_RUN_AS_ROOT": "1",
                "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM": "1"
              }
            }
          }
        ],
        "computeResource": {
          "cpuMilli": "$cpu_milli",
          "memoryMib": "$memory_mib"
        },
        "maxRunDuration": "10800s"
      },
      "taskCount": 1
    }
  ],
  "allocationPolicy": {
    "instances": [
      {
        "policy": {
          "machineType": "$machine",
          "provisioningModel": "STANDARD",
          "bootDisk": {
            "sizeGb": "50"
          }
        }
      }
    ]
  },
  "logsPolicy": {
    "destination": "CLOUD_LOGGING"
  }
}
EOF

  gcloud batch jobs submit "$job_id_safe" \
    --location=europe-west1 \
    --config="/tmp/${job_id_safe}.json" \
    --project=predsea-api
done

echo "✅ All 5 regional 24h WW3 forecast jobs successfully submitted!"
