#!/usr/bin/env bash
# PredSea Spot VM Startup Script (DEBUG MODE - NO SELF-DELETION)
# Configured to run on standard Debian/Ubuntu GCE instances.
set -euo pipefail

# 1. Variables (injected via metadata at creation)
PROJECT_ID=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/project/project-id)
ZONE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $4}')
NAME=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)

cleanup() {
  echo "============================================="
  echo "⚠️ Cleanup Triggered (Debug Mode: keeping VM alive for inspection)"
  echo "============================================="
  # Ensure all workspace outputs/logs are uploaded to GCS before ending startup script
  if [ -d /workspace/outputs ] && [ -n "${GCS_BUCKET:-}" ] && [ -n "${RUN_DATE:-}" ] && [ -n "${RUN_ID:-}" ]; then
    echo "Syncing final /workspace/outputs/ to GCS..."
    gsutil -m rsync -r /workspace/outputs/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/" || true
  fi
}
trap cleanup EXIT

echo "============================================="
echo "🚀 PredSea VM Startup Script Initialized (DEBUG MODE)"
echo "============================================="

GCS_BUCKET=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/gcs-bucket || echo "predsea-daily-outputs")
RUN_DATE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/run-date || date -u +"%Y-%m-%d")
RUN_ID=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/run-id || date -u +"%Y-%m-%dT%H%MZ")
IMAGE_TAG=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/image-tag || echo "latest")

DOCKER_IMAGE="europe-west1-docker.pkg.dev/${PROJECT_ID}/predsea-simulations/wrf:${IMAGE_TAG}"

echo "Project ID: ${PROJECT_ID}"
echo "Instance: ${NAME} in zone ${ZONE}"
echo "Target Date/Run: ${RUN_DATE} / ${RUN_ID}"
echo "Docker Image: ${DOCKER_IMAGE}"
echo "============================================="

# 2. Install Docker if not already installed
if ! command -v docker &> /dev/null; then
  echo "Installing Docker..."
  apt-get update
  apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bullseye stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io
fi

# 3. Configure Docker credential helper for Artifact Registry
echo "Configuring docker credentials..."
gcloud auth configure-docker europe-west1-docker.pkg.dev --quiet

# 4. Pull WRF/ROMS model image
echo "Pulling model container image..."
docker pull "${DOCKER_IMAGE}"

# 5. Create workspaces and download forcing data (e.g. ECMWF and CMEMS inputs)
mkdir -p /workspace/inputs
mkdir -p /workspace/outputs
mkdir -p /workspace/inputs/static
mkdir -p /workspace/bin

# Download ECMWF and CMEMS boundary forcing files from GCS paths
echo "Downloading atmospheric boundary conditions from GCS..."
gsutil -m rsync -r "gs://${GCS_BUCKET}/forcing/ecmwf/${RUN_DATE}/" /workspace/inputs/

echo "Downloading oceanic boundary conditions from GCS..."
gsutil -m rsync -r "gs://${GCS_BUCKET}/forcing/cmems/${RUN_DATE}/" /workspace/inputs/

echo "Downloading compiled NEMO and SWAN binaries from GCS..."
gsutil cp "gs://${GCS_BUCKET}/binaries/nemo.exe" /workspace/bin/nemo.exe || echo "⚠️ Warning: nemo.exe not found in GCS. Skipping."
gsutil cp "gs://${GCS_BUCKET}/binaries/swan.exe" /workspace/bin/swan.exe || echo "⚠️ Warning: swan.exe not found in GCS. Skipping."

if [ -f /workspace/bin/nemo.exe ] || [ -f /workspace/bin/swan.exe ]; then
  chmod +x /workspace/bin/nemo.exe /workspace/bin/swan.exe || true
fi

echo "Downloading static bathymetry grids from GCS..."
gsutil cp "gs://${GCS_BUCKET}/static/bathymetry/balearic_bathymetry_nemo.nc" /workspace/inputs/static/balearic_bathymetry_nemo.nc || echo "⚠️ Warning: balearic_bathymetry_nemo.nc not found in GCS. Skipping."
gsutil cp "gs://${GCS_BUCKET}/static/bathymetry/balearic_bathymetry_swan.nc" /workspace/inputs/static/balearic_bathymetry_swan.nc || echo "⚠️ Warning: balearic_bathymetry_swan.nc not found in GCS. Skipping."

# 6. Run the simulation pipeline container
echo "Executing model simulation..."

# Run docker, teeing output to both console and a log file
set +e
docker run --rm \
  -v /workspace/inputs:/data \
  -v /workspace/outputs:/workspace/run \
  -v /workspace/bin:/bin_mount \
  "${DOCKER_IMAGE}" \
  /opt/predsea/run_pipeline.sh 2>&1 | tee /workspace/outputs/docker_run.log
DOCKER_EXIT_CODE=${PIPESTATUS[0]}
set -e

if [ $DOCKER_EXIT_CODE -ne 0 ]; then
  echo "❌ Error: Docker container failed with exit code $DOCKER_EXIT_CODE."
  echo "=================== DOCKER RUN FAILURE LOG DUMP ==================="
  cat /workspace/outputs/docker_run.log || true
  echo "==================================================================="
  # Upload logs before exiting so they are archived even on failure
  echo "Uploading failure logs and outputs to GCS..."
  gsutil -m rsync -r /workspace/outputs/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/" || true
  exit $DOCKER_EXIT_CODE
fi

# 7. Upload outputs back to GCS
echo "Uploading outputs to GCS..."
gsutil -m rsync -r /workspace/outputs/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/"

echo "============================================="
echo "🎉 Simulation pipeline complete!"
echo "============================================="
