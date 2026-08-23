#!/usr/bin/env bash
# PredSea basin-wide SWAN VM startup script.
#
# Runs ONLY the basin-wide SWAN pass (see gcp_orchestrator.py --vm-role=basin-swan
# and simulation/marine/regions/med_basin_1km.json) on its own dedicated VM,
# fully separate from the WRF VM (vm_startup.sh). This VM is launched by
# daily_orchestrator.py only after the WRF VM has finished and self-deleted,
# so the two never compete for the 64-vCPU CPUS_ALL_REGIONS project quota at
# the same time. It writes BASIN_SWAN_SUCCESS (not SUCCESS -- that marker is
# WRF's exclusive signal, and daily_orchestrator.py's CROCO Batch submissions
# key off it) and self-deletes on success, mirroring vm_startup.sh's pattern.
set -euo pipefail

# 1. Variables (injected via metadata at creation)
PROJECT_ID=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/project/project-id)
ZONE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $4}')
NAME=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)

GCS_BUCKET=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/gcs-bucket || echo "predsea-daily-outputs")
RUN_DATE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/run-date || date -u +"%Y-%m-%d")
RUN_ID=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/run-id || date -u +"%Y-%m-%dT%H%MZ")
FORECAST_HOURS=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/forecast-hours || echo "24")

BASIN_SWAN_REGION=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/basin-swan-region 2>/dev/null || echo "")
BASIN_SWAN_IMAGE_URI=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/basin-swan-image-uri 2>/dev/null || echo "")
BASIN_SWAN_MPI_RANKS=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/basin-swan-mpi-ranks 2>/dev/null || echo "64")
COPERNICUS_USERNAME=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/copernicus-username 2>/dev/null || echo "")
COPERNICUS_PASSWORD=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/copernicus-password 2>/dev/null || echo "")

if [ -z "${BASIN_SWAN_REGION}" ] || [ -z "${BASIN_SWAN_IMAGE_URI}" ]; then
  echo "❌ vm_startup_basin_swan.sh requires basin-swan-region and basin-swan-image-uri metadata; got region='${BASIN_SWAN_REGION}' image='${BASIN_SWAN_IMAGE_URI}'."
  exit 2
fi

# Successful instances self-delete. Failed instances preserve their boot disk
# and stop so diagnostics remain available without continuing CPU charges.
cleanup() {
  local exit_code=$?
  echo "============================================="
  echo "⚠️ Cleanup Triggered with exit code ${exit_code}."
  echo "============================================="

  if [[ ${exit_code} -ne 0 ]] && [ -d /workspace/outputs ]; then
    cat > /workspace/outputs/BASIN_SWAN_FAILURE <<EOF
status=FAILURE
exit_code=${exit_code}
instance=${NAME}
zone=${ZONE}
run_date=${RUN_DATE}
run_id=${RUN_ID}
timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
  fi

  if [ -d /workspace/outputs ] && [ -n "${GCS_BUCKET:-}" ] && [ -n "${RUN_DATE:-}" ] && [ -n "${RUN_ID:-}" ]; then
    echo "Syncing final /workspace/outputs/ to GCS..."
    gsutil -m rsync -r /workspace/outputs/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/" || true
    if [ -f /workspace/outputs/startup.log ]; then
      gsutil cp /workspace/outputs/startup.log "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/basin_swan_startup.log" || true
    fi
  fi

  if [[ "${NAME}" == *debug* ]]; then
    echo "ℹ️ Debug instance detected. Bypassing VM self-deletion to allow inspection."
  elif [[ ${exit_code} -eq 0 ]]; then
    echo "✅ Successful workload; deleting completed VM."
    gcloud compute instances delete "${NAME}" --zone="${ZONE}" --quiet || true
  else
    echo "🛑 Failed workload; stopping VM and preserving its boot disk for diagnostics."
    shutdown -h now || true
  fi
}
trap cleanup EXIT

echo "============================================="
echo "🌊 PredSea Basin-wide SWAN VM Startup Script Initialized"
echo "Project ID: ${PROJECT_ID}"
echo "Instance: ${NAME} in zone ${ZONE}"
echo "Region: ${BASIN_SWAN_REGION} | MPI ranks: ${BASIN_SWAN_MPI_RANKS}"
echo "Target Date/Run: ${RUN_DATE} / ${RUN_ID}"
echo "Forecast horizon: ${FORECAST_HOURS}h"
echo "============================================="

mkdir -p /workspace/inputs
mkdir -p /workspace/outputs

# Redirect all output to a log file as well as stdout for debugging
exec > >(tee -a /workspace/outputs/startup.log) 2>&1

# Basin-wide SWAN needs the same ECMWF wind window WRF's VM used (SWAN reads
# the raw GRIB2 directly, not WRF's output) -- CMEMS wave boundary data is
# fetched directly inside the container by fetch_native_marine_forcing.py,
# so syncing it here is optional but harmless for consistency/debugging.
echo "Downloading atmospheric boundary conditions from GCS..."
gsutil -m rsync -r "gs://${GCS_BUCKET}/forcing/ecmwf/${RUN_DATE}/" /workspace/inputs/ || echo "⚠️ Warning: Atmospheric boundary forcing not found."
echo "Downloading oceanic boundary conditions from GCS..."
gsutil -m rsync -r "gs://${GCS_BUCKET}/forcing/cmems/${RUN_DATE}/" /workspace/inputs/ || echo "⚠️ Warning: Oceanic boundary forcing not found."

# Install Docker (this is a fresh VM -- nothing pre-installed)
if ! command -v docker &> /dev/null; then
  echo "Installing Docker..."
  apt-get update
  apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release

  DISTRO_CODENAME=$(lsb_release -cs 2>/dev/null || echo "bullseye")
  DISTRO_ID=$(lsb_release -is 2>/dev/null | tr '[:upper:]' '[:lower:]' || echo "debian")

  mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/${DISTRO_ID}/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg || true

  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${DISTRO_ID} ${DISTRO_CODENAME} stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io || apt-get install -y docker.io
fi

# Configure Docker credential helper for Artifact Registry
echo "Configuring docker credentials..."
gcloud auth configure-docker europe-west1-docker.pkg.dev --quiet

echo "============================================="
echo "🌊 Running basin-wide SWAN (region=${BASIN_SWAN_REGION}, ${BASIN_SWAN_MPI_RANKS} ranks)..."
echo "============================================="
set +e
docker pull "${BASIN_SWAN_IMAGE_URI}"
docker run --rm \
  --network=host \
  --shm-size=8gb \
  -e PREDSEA_RUN_DATE="${RUN_DATE}" \
  -e PREDSEA_RUN_ID="${RUN_ID}" \
  -e OMPI_ALLOW_RUN_AS_ROOT=1 \
  -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
  -e COPERNICUS_USERNAME="${COPERNICUS_USERNAME}" \
  -e COPERNICUS_PASSWORD="${COPERNICUS_PASSWORD}" \
  -e COPERNICUSMARINE_SERVICE_USERNAME="${COPERNICUS_USERNAME}" \
  -e COPERNICUSMARINE_SERVICE_PASSWORD="${COPERNICUS_PASSWORD}" \
  "${BASIN_SWAN_IMAGE_URI}" \
  --region "${BASIN_SWAN_REGION}" \
  --model swan \
  --forecast-hours "${FORECAST_HOURS}" \
  --mpi-ranks "${BASIN_SWAN_MPI_RANKS}" \
  --gcs-bucket "${GCS_BUCKET}" \
  2>&1 | tee /workspace/outputs/basin_swan_run.log
BASIN_SWAN_EXIT_CODE=${PIPESTATUS[0]}
set -e

if [ ${BASIN_SWAN_EXIT_CODE} -ne 0 ]; then
  echo "❌ Error: Basin-wide SWAN failed with exit code ${BASIN_SWAN_EXIT_CODE}."
  exit ${BASIN_SWAN_EXIT_CODE}
fi

echo "✅ Basin-wide SWAN finished; cropping into per-region files..."
# --entrypoint override is required: the image's baked-in ENTRYPOINT is
# ["python3", "/app/scripts/run_marine_simulation.py"] (see
# simulation/marine/croco/Dockerfile.batch), so without this, "bash -c ..."
# would be appended as extra arguments to that entrypoint instead of
# actually running bash.
# crop_basin_swan_output.py's own --gcs-bucket upload option needs the
# google-cloud-storage Python package, which isn't in this image's
# requirements.batch.txt (only gsutil, via the bundled Cloud SDK, is). Crop
# locally only and let gsutil handle each resulting file's upload.
set +e
docker run --rm \
  --network=host \
  --entrypoint bash \
  "${BASIN_SWAN_IMAGE_URI}" \
  -c "gsutil cp gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/${BASIN_SWAN_REGION}/${BASIN_SWAN_REGION}_swan_forecast.nc /tmp/basin.nc && \
    python3 /app/scripts/crop_basin_swan_output.py \
      --basin-file /tmp/basin.nc \
      --output-dir /tmp/cropped && \
    for f in /tmp/cropped/*_swan_forecast.nc; do \
      region=\$(basename \"\$f\" _swan_forecast.nc); \
      gsutil cp \"\$f\" \"gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/\${region}/\${region}_swan_forecast.nc\"; \
    done" \
  2>&1 | tee -a /workspace/outputs/basin_swan_run.log
CROP_EXIT_CODE=${PIPESTATUS[0]}
set -e
if [ ${CROP_EXIT_CODE} -ne 0 ]; then
  echo "❌ Error: Crop-to-regions step failed with exit code ${CROP_EXIT_CODE}. The basin-wide file itself is still on GCS for manual recovery."
  exit ${CROP_EXIT_CODE}
fi
echo "✅ Cropped basin-wide SWAN output into 5 regional files on GCS."

echo "Uploading generic outputs and logs to GCS..."
gsutil -m rsync -r /workspace/outputs/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/" || true

echo "Uploading BASIN_SWAN_SUCCESS marker file to GCS..."
echo "SUCCESS" > /tmp/BASIN_SWAN_SUCCESS
gsutil cp /tmp/BASIN_SWAN_SUCCESS "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/BASIN_SWAN_SUCCESS"

echo "============================================="
echo "🎉 Basin-wide SWAN pipeline complete!"
echo "============================================="
