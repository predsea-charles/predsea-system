#!/bin/bash
set -euo pipefail

# PredSea WW3 24h Forecast Post-Processing Submission Script
# Enforces immutable image digest and run-scoped script staging URI.

GCS_FORCING_BASE="gs://predsea-daily-outputs-test/scratch"
REGIONS=("alboran_1km" "gulf_of_lion_1km" "balearic_1km" "algerian_1km" "tyrrhenian_1km")

# Immutable image digest for ww3-batch container
IMAGE_URI="europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/ww3-batch@sha256:0172a64ac9b4a42399e59643ecdc1e7c03366b614b1d608f171b37aafe6d621c"

TIMESTAMP="$(date +%s)"
SCRIPT_STAGING_URI="${GCS_FORCING_BASE}/runs/ww3-postproc-${TIMESTAMP}/postprocess_ww3.py"

echo "Staging scripts/postprocess_ww3.py to run-scoped GCS URI: ${SCRIPT_STAGING_URI}..."
gsutil cp scripts/postprocess_ww3.py "${SCRIPT_STAGING_URI}"

echo "========================================================================"
echo "🚀 Submitting WW3 NetCDF Post-Processing Python Jobs for All 5 Regions"
echo "Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Image Digest: ${IMAGE_URI}"
echo "Script URI: ${SCRIPT_STAGING_URI}"
echo "========================================================================"

for region in "${REGIONS[@]}"; do
  job_id_safe="ww3-postproc-${region//_/-}-${TIMESTAMP}"
  echo "Submitting post-processing job for '$region'..."

  cat > "/tmp/${job_id_safe}.json" << EOF
{
  "taskGroups": [
    {
      "taskSpec": {
        "runnables": [
          {
            "container": {
              "imageUri": "${IMAGE_URI}",
              "entrypoint": "/bin/bash",
              "commands": [
                "-c",
                "set -ex; mkdir -p /workspace/scripts && gsutil cp '${SCRIPT_STAGING_URI}' /workspace/scripts/postprocess_ww3.py && PYTHONUNBUFFERED=1 python3 /workspace/scripts/postprocess_ww3.py --region $region"
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
          "provisioningModel": "STANDARD"
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

echo "✅ All 5 regional post-processing jobs successfully submitted!"
