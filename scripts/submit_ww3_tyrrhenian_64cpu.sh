#!/bin/bash
set -euo pipefail

# Submit 24h WW3 Forecast for Region 5: tyrrhenian_1km (64 vCPUs)
GCS_FORCING_BASE="gs://predsea-daily-outputs-test/scratch/ww3-24h-test"
GCS_GRID_BASE="gs://predsea-daily-outputs-test/scratch/ww3-smoke-test"
GCS_OUTPUT_BASE="gs://predsea-daily-outputs-test/predictions/2026-08-05/runs/ww3-24h-forecast"

region="tyrrhenian_1km"
MACHINE_TYPE="n2-custom-64-65536"
CORES=64
TIMESTAMP="$(date +%s)"

job_id_safe="ww3-24h-${region//_/-}-64cpu-${TIMESTAMP}"
echo "=== Submitting 24h WW3 forecast for region '$region' ($CORES vCPU $MACHINE_TYPE) ==="

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
              "options": "--shm-size=16g",
              "commands": [
                "-c",
                "exec > >(tee -a run_trace.log) 2>&1; set -ex; mkdir -p /workspace/ww3 && cd /workspace/ww3; ( while true; do sleep 15; gsutil -q cp run_trace.log ${GCS_OUTPUT_BASE}/$region-output/run_trace.log >/dev/null 2>&1 || true; done ) & LOGGER_PID=\$!; echo '[STEP 1/5] Downloading grid model files...'; gsutil cp ${GCS_GRID_BASE}/$region/mod_def.ww3 . ; echo '[STEP 2/5] Downloading wind forcing files...'; gsutil cp ${GCS_FORCING_BASE}/$region/wind.nc . && gsutil cp ${GCS_FORCING_BASE}/$region/ww3_prnc.nml . && gsutil cp ${GCS_FORCING_BASE}/$region/ww3_shel.nml . ; echo '[STEP 3/5] Preprocessing wind forcing via ww3_prnc...'; ww3_prnc ; echo '[STEP 4/5] Executing Wavewatch III forecast solver (ww3_shel) on $CORES cores...'; mpirun --allow-run-as-root --use-hwthread-cpus -np $CORES ww3_shel ; echo '[STEP 5/5] Uploading forecast outputs to GCS...'; echo 'status=SUCCESS' > FORECAST_RESULT.txt ; kill \$LOGGER_PID 2>/dev/null || true; gsutil cp -r /workspace/ww3 ${GCS_OUTPUT_BASE}/$region-output ; echo '[COMPLETE] 24h Forecast completed successfully!'"
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
          "cpuMilli": "64000",
          "memoryMib": "65536"
        },
        "maxRunDuration": "28800s"
      },
      "taskCount": 1
    }
  ],
  "allocationPolicy": {
    "instances": [
      {
        "policy": {
          "machineType": "$MACHINE_TYPE",
          "provisioningModel": "STANDARD",
          "bootDisk": {
            "sizeGb": "100"
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

echo "✅ Tyrrhenian 1km 64-vCPU job '$job_id_safe' successfully submitted!"
