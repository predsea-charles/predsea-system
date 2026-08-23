#!/bin/bash
set -euo pipefail

RUN_ID="${1:-2026-08-05T2131Z}"
RUN_DATE="${2:-2026-08-05}"
GCS_WRF_PATH="gs://predsea-daily-outputs-test/predictions/${RUN_DATE}/runs/${RUN_ID}/"
GCS_TARGET_BASE="gs://predsea-daily-outputs-test/scratch/ww3-24h-test/"
GCS_SCRIPT_PATH="gs://predsea-daily-outputs-test/scratch/scripts/prepare_ww3_wind_from_wrf.py"

JOB_NAME="ww3-wind-prep-$(date +%s)"

echo "Staging prepare_ww3_wind_from_wrf.py script to GCS..."
gsutil cp scripts/prepare_ww3_wind_from_wrf.py "${GCS_SCRIPT_PATH}"

echo "Submitting GCP Batch job '${JOB_NAME}' to generate WW3 wind forcing in the cloud..."
echo "  Input: ${GCS_WRF_PATH}"
echo "  Target: ${GCS_TARGET_BASE}"

cat > "/tmp/${JOB_NAME}.json" << EOF
{
  "taskGroups": [
    {
      "taskSpec": {
        "runnables": [
          {
            "container": {
              "imageUri": "europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/ww3-batch:latest",
              "entrypoint": "/bin/bash",
              "commands": [
                "-c",
                "set -ex; mkdir -p /workspace/wrf /workspace/ww3_forcing /workspace/scripts && gsutil cp '${GCS_SCRIPT_PATH}' /workspace/scripts/prepare_ww3_wind_from_wrf.py && gsutil -m cp '${GCS_WRF_PATH}wrfout_d02_*' /workspace/wrf/ && PYTHONUNBUFFERED=1 python3 /workspace/scripts/prepare_ww3_wind_from_wrf.py --wrf-dir /workspace/wrf --output-base-dir /workspace/ww3_forcing && gsutil -m cp -r /workspace/ww3_forcing/* '${GCS_TARGET_BASE}'"
              ]
            }
          }
        ],
        "computeResource": {
          "cpuMilli": "4000",
          "memoryMib": "8192"
        },
        "maxRunDuration": "1800s"
      },
      "taskCount": 1
    }
  ],
  "allocationPolicy": {
    "instances": [
      {
        "policy": {
          "machineType": "e2-standard-4",
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

gcloud batch jobs submit "${JOB_NAME}" \
  --location=europe-west1 \
  --config="/tmp/${JOB_NAME}.json" \
  --project=predsea-api

echo "✅ Job '${JOB_NAME}' successfully submitted!"
