#!/bin/bash
set -euo pipefail

source .venv311/bin/activate

# Upload forcing files for the 4 new regions (alboran_1km's are already in GCS)
for region in algerian_1km balearic_1km tyrrhenian_1km gulf_of_lion_1km; do
  gsutil -m cp \
    "simulation/marine/ww3/grids/$region/wind.nc" \
    "simulation/marine/ww3/grids/$region/ww3_prnc.nml" \
    "simulation/marine/ww3/grids/$region/ww3_shel.nml" \
    "simulation/marine/ww3/grids/$region/forcing_manifest.json" \
    "gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region/"
done

# Submit all 5 regions as 16-vCPU Batch jobs (n2-highcpu-16, --shm-size=8g).
# 5 x 16 = 80 vCPU requested against a 64 vCPU ceiling: Batch will run 4
# concurrently and auto-queue the 5th until a slot frees, no action needed.
for region in alboran_1km algerian_1km balearic_1km tyrrhenian_1km gulf_of_lion_1km; do
  echo "=== submitting 6h smoke test for $region (16 vCPU) ==="

  cat > "/tmp/ww3-smoke-$region.json" << EOF
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
                "set -x; mkdir -p /workspace/ww3 && cd /workspace/ww3 && ( gsutil -m cp -r 'gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region/*' . && ww3_prnc && mpirun --allow-run-as-root --use-hwthread-cpus -np 16 ww3_shel && echo status=SUCCESS > SMOKE_TEST_RESULT.txt || echo status=FAILED > SMOKE_TEST_RESULT.txt ) > /workspace/ww3/run_trace.log 2>&1; gsutil -m cp -r /workspace/ww3/* gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region-output/"
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
          "cpuMilli": "16000",
          "memoryMib": "16384"
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
          "machineType": "n2-highcpu-16",
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

  job_id_safe="ww3-smoke-${region//_/-}-$(date +%s)"
  gcloud batch jobs submit "$job_id_safe" \
    --location=europe-west1 --config="/tmp/ww3-smoke-$region.json" --project=predsea-api
done
