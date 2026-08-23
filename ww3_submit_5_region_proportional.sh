#!/bin/bash
set -euo pipefail

source .venv311/bin/activate

# ---------------------------------------------------------------------------
# Proportional core split, based on actual sea-point counts from each
# region's ww3_grid run (not bbox size / intuition):
#   tyrrhenian_1km : 364,101 sea points -> 24 vCPU
#   balearic_1km   : 231,349 sea points -> 16 vCPU
#   algerian_1km   : 158,683 sea points -> 12 vCPU
#   alboran_1km    :  ~87,000 sea points ->  8 vCPU (estimate; alboran's grid
#                     step ran locally before we switched to cloud-only, so
#                     we don't have its exact sea-point count logged)
#   gulf_of_lion_1km:  73,874 sea points ->  4 vCPU
# Total: 64 vCPU, matches the project ceiling exactly -- all 5 run
# concurrently, no queuing.
#
# maxRunDuration is set generously to 3 hours (10800s) given the 16-core
# timeout: at 16 cores every region was still running (not crashed) when
# Batch killed it at 1800s, so actual runtime at these proportional core
# counts is genuinely unknown -- 3 hours gives real headroom.
#
# Each container also runs a background loop that re-uploads run_trace.log
# every 30s, so if a job times out again we still get a recent snapshot of
# how far it got, instead of zero visibility like last time.
#
# NOTE: no associative arrays here (declare -A) -- macOS's default /bin/bash
# is 3.2, which predates bash 4's associative-array support. Using a plain
# "region:cores:machine" string list instead, which works on any bash.
# ---------------------------------------------------------------------------

REGION_SPECS="tyrrhenian_1km:24:n2-custom-24-24576 balearic_1km:16:n2-highcpu-16 algerian_1km:12:n2-custom-12-12288 alboran_1km:8:n2-highcpu-8 gulf_of_lion_1km:4:n2-highcpu-4"

for entry in $REGION_SPECS; do
  region="${entry%%:*}"
  rest="${entry#*:}"
  cores="${rest%%:*}"
  machine="${rest#*:}"
  cpu_milli=$((cores * 1000))
  memory_mib=$((cores * 1024))

  echo "=== submitting 6h smoke test for $region ($cores vCPU, $machine) ==="

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
                "set -x; mkdir -p /workspace/ww3 && cd /workspace/ww3 && gsutil -m cp -r 'gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region/*' . ; ( while true; do sleep 30; gsutil -q cp run_trace.log gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region-output/run_trace.log >/dev/null 2>&1 || true; done ) & LOGGER_PID=\$!; ( ww3_prnc && mpirun --allow-run-as-root --use-hwthread-cpus -np $cores ww3_shel && echo status=SUCCESS > SMOKE_TEST_RESULT.txt || echo status=FAILED > SMOKE_TEST_RESULT.txt ) > run_trace.log 2>&1; kill \$LOGGER_PID 2>/dev/null; gsutil -m cp -r /workspace/ww3/* gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region-output/"
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
