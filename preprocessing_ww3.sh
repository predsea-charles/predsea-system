#!/bin/bash
set -euo pipefail

source .venv311/bin/activate

# ---------------------------------------------------------------------------
# Step 0: physics table needed by every region (ST4 source term package).
# Already generated for alboran_1km; just copy it into the 4 new regions.
# ---------------------------------------------------------------------------
for region in algerian_1km balearic_1km tyrrhenian_1km gulf_of_lion_1km; do
  mkdir -p "simulation/marine/ww3/grids/$region"
  cp "simulation/marine/ww3/grids/alboran_1km/ST4TABUHF2.bin" \
     "simulation/marine/ww3/grids/$region/ST4TABUHF2.bin"
done

# ---------------------------------------------------------------------------
# Step 1: local grid + forcing prep for the 4 new regions (alboran_1km
# already done in an earlier run). Reuses the existing ECMWF wind GRIB
# (global coverage) instead of re-fetching per region.
# ---------------------------------------------------------------------------
for region in algerian_1km balearic_1km tyrrhenian_1km gulf_of_lion_1km; do
  echo "=== prepping $region ==="
  python3 scripts/prepare_ww3_grid.py --region "$region" --output-dir "simulation/marine/ww3/grids/$region"
  python3 scripts/prepare_ww3_forcing.py --region "$region" \
    --wind-grib /tmp/ecmwf_wind_alboran_smoke.grib2 \
    --output-dir "simulation/marine/ww3/grids/$region" \
    --start-time 2026-08-04T00:00:00 --forecast-hours 6
done

# ---------------------------------------------------------------------------
# Step 2: upload grid inputs to GCS and submit a lightweight ww3_grid Batch
# job per region (non-MPI preprocessor, 2 vCPU is plenty).
# ---------------------------------------------------------------------------
for region in algerian_1km balearic_1km tyrrhenian_1km gulf_of_lion_1km; do
  echo "=== uploading + submitting ww3_grid job for $region ==="
  gsutil -m cp \
    "simulation/marine/ww3/grids/$region/ww3_grid.nml" \
    "simulation/marine/ww3/grids/$region/depth.inp" \
    "simulation/marine/ww3/grids/$region/namelists.nml" \
    "simulation/marine/ww3/grids/$region/ST4TABUHF2.bin" \
    "gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region/"

  job_id_safe="ww3-grid-${region//_/-}-$(date +%s)"

  cat > "/tmp/ww3-grid-$region.json" << EOF
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
                "set -x; mkdir -p /workspace/ww3grid && cd /workspace/ww3grid && ( gsutil -m cp -r 'gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region/*' . && ww3_grid && echo status=SUCCESS > GRID_RESULT.txt || echo status=FAILED > GRID_RESULT.txt ) > run_trace.log 2>&1; gsutil -m cp -r /workspace/ww3grid/* gs://predsea-daily-outputs-test/scratch/ww3-smoke-test/$region/"
              ]
            }
          }
        ],
        "computeResource": {
          "cpuMilli": "2000",
          "memoryMib": "4096"
        },
        "maxRunDuration": "600s"
      },
      "taskCount": 1
    }
  ],
  "allocationPolicy": {
    "instances": [
      {
        "policy": {
          "machineType": "e2-standard-2",
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
    --location=europe-west1 --config="/tmp/ww3-grid-$region.json" --project=predsea-api
done
