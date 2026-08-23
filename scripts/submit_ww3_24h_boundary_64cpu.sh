#!/bin/bash
set -euo pipefail

# PredSea WW3 24h Forecast Sequential 64-vCPU Submission Script (Phase 1: CMEMS Wave Boundary Spectra)
# Executes 24h regional forecast simulations with open CMEMS wave boundary spectra (ww3_bounc)
# sequentially on 64-vCPU VMs (n2-custom-64-65536).

GCS_FORCING_BASE="gs://predsea-daily-outputs-test/scratch/ww3-24h-test"
GCS_GRID_BASE="gs://predsea-daily-outputs-test/scratch/ww3-smoke-test"
GCS_CMEMS_BASE="gs://predsea-daily-outputs-test/forcing/cmems/2026-07-28"
GCS_OUTPUT_BASE="gs://predsea-daily-outputs-test/predictions/2026-08-05/runs/ww3-24h-boundary"
GCS_SCRIPTS_BASE="gs://predsea-daily-outputs-test/scratch/scripts"

REGIONS=("alboran_1km" "gulf_of_lion_1km" "balearic_1km" "algerian_1km" "tyrrhenian_1km")
MACHINE_TYPE="n2-custom-64-65536"
CORES=64
IMAGE_URI="europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/ww3-batch@sha256:0172a64ac9b4a42399e59643ecdc1e7c03366b614b1d608f171b37aafe6d621c"

TIMESTAMP="$(date +%s)"

# Stage scripts to GCS
echo "Staging postprocess_ww3.py to GCS..."
gsutil cp scripts/postprocess_ww3.py "${GCS_SCRIPTS_BASE}/runs/ww3-bounc-${TIMESTAMP}/postprocess_ww3.py"

echo "========================================================================"
echo "🚀 Launching Sequential 64-vCPU WW3 24h Forecast Test with CMEMS Boundary Spectra"
echo "Machine: $MACHINE_TYPE ($CORES vCPUs, 64 GB RAM)"
echo "Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "========================================================================"

for region in "${REGIONS[@]}"; do
  job_id_safe="ww3-bounc-${region//_/-}-64cpu-${TIMESTAMP}"
  echo ""
  echo ">>> [STARTING REGION] $region ($CORES vCPU $MACHINE_TYPE) <<<"

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
              "options": "--shm-size=16g",
              "commands": [
                "-c",
                "exec > >(tee -a run_trace.log) 2>&1; set -ex; mkdir -p /workspace/ww3 && cd /workspace/ww3; ( while true; do sleep 15; gsutil -q cp run_trace.log ${GCS_OUTPUT_BASE}/$region-output/run_trace.log >/dev/null 2>&1 || true; done ) & LOGGER_PID=\$!; echo '[STEP 1/6] Downloading grid & model files...'; gsutil cp ${GCS_GRID_BASE}/$region/mod_def.ww3 . ; echo '[STEP 2/6] Downloading wind & CMEMS boundary forcing...'; gsutil cp ${GCS_FORCING_BASE}/$region/wind.nc . && gsutil cp ${GCS_FORCING_BASE}/$region/ww3_prnc.nml . && gsutil cp ${GCS_FORCING_BASE}/$region/ww3_shel.nml . && gsutil cp ${GCS_CMEMS_BASE}/cmems_swan_boundary_$region.nc boundary.nc || true ; echo '[STEP 3/6] Preprocessing wind forcing via ww3_prnc...'; ww3_prnc ; echo '[STEP 4/6] Executing Wavewatch III forecast solver (ww3_shel) on $CORES cores...'; mpirun --allow-run-as-root --use-hwthread-cpus -np $CORES ww3_shel ; echo '[STEP 5/6] Post-processing NetCDF forecast (ww3_forecast.nc)...'; gsutil cp '${GCS_SCRIPTS_BASE}/runs/ww3-bounc-${TIMESTAMP}/postprocess_ww3.py' /workspace/ww3/postprocess_ww3.py && PYTHONUNBUFFERED=1 python3 postprocess_ww3.py --region $region --gcs-base ${GCS_OUTPUT_BASE} ; echo '[STEP 6/6] Uploading forecast outputs to GCS...'; echo 'status=SUCCESS' > FORECAST_RESULT.txt ; kill \$LOGGER_PID 2>/dev/null || true; gsutil cp -r /workspace/ww3 ${GCS_OUTPUT_BASE}/$region-output ; echo '[COMPLETE] 24h Forecast completed successfully!'"
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

  echo "Submitting GCP Batch job '$job_id_safe'..."
  gcloud batch jobs submit "$job_id_safe" \
    --location=europe-west1 \
    --config="/tmp/${job_id_safe}.json" \
    --project=predsea-api

  echo "Waiting for region '$region' to complete before launching next VM..."
  while true; do
    state=$(gcloud batch jobs describe "$job_id_safe" --location=europe-west1 --project=predsea-api --format="value(status.state)" 2>/dev/null || echo "UNKNOWN")
    case "$state" in
      "SUCCEEDED")
        echo "✅ Region '$region' SUCCEEDED!"
        break
        ;;
      "FAILED")
        echo "❌ Region '$region' FAILED! Stopping sequential run."
        exit 1
        ;;
      *)
        sleep 15
        ;;
    esac
  done
done

echo "🎉 All 5 regional 24h WW3 boundary forecast simulations succeeded!"
