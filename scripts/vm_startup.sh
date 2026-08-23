#!/usr/bin/env bash
# PredSea Spot VM Startup Script
# Configured to run on standard Debian/Ubuntu GCE instances.
set -euo pipefail

# 1. Variables (injected via metadata at creation)
PROJECT_ID=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/project/project-id)
ZONE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $4}')
NAME=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)

GCS_BUCKET=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/gcs-bucket || echo "predsea-daily-outputs")
RUN_DATE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/run-date || date -u +"%Y-%m-%d")
RUN_ID=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/run-id || date -u +"%Y-%m-%dT%H%MZ")
IMAGE_TAG=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/image-tag || echo "latest")
IMAGE_URI=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/image-uri || true)
EXECUTION_MODE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/execution-mode || echo "container")
FORECAST_HOURS=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/forecast-hours || echo "24")
END_DATE=$(date -u -d "${RUN_DATE} 00:00:00 UTC + ${FORECAST_HOURS} hours" +%Y-%m-%d_%H:%M:%S)

# Basin-wide SWAN (if enabled for this run) runs on its own separate VM via
# vm_startup_basin_swan.sh, launched only after this WRF VM has fully
# finished and self-deleted -- not on this VM. Reusing this VM for both used
# to save on GCP quota, but kept it alive (holding its full 64-vCPU
# CPUS_ALL_REGIONS allocation) for however long basin-wide SWAN took
# (observed 8+ hours), which then starved CROCO's own per-region Batch job
# submissions of quota the moment they were unblocked. Strict serialization
# across 3 separate VM lifecycles (WRF -> delete -> basin-SWAN -> delete ->
# CROCO, throttled) avoids that conflict entirely, at the cost of total
# wall-clock time.

if [[ -n "${IMAGE_URI}" ]]; then
  case "${IMAGE_URI}" in
    *@sha256:*) DOCKER_IMAGE="${IMAGE_URI}" ;;
    *) echo "Refusing unpinned image-uri metadata: ${IMAGE_URI}" >&2; exit 2 ;;
  esac
else
  DOCKER_IMAGE="europe-west1-docker.pkg.dev/${PROJECT_ID}/predsea-simulations/wrf:${IMAGE_TAG}"
fi

# Successful instances self-delete. Failed instances preserve their boot disk
# and stop so diagnostics remain available without continuing CPU charges.
cleanup() {
  local exit_code=$?
  echo "============================================="
  echo "⚠️ Cleanup Triggered with exit code ${exit_code}."
  echo "============================================="

  if [[ ${exit_code} -ne 0 ]] && [ -d /workspace/outputs ]; then
    cat > /workspace/outputs/FAILURE <<EOF
status=FAILURE
exit_code=${exit_code}
instance=${NAME}
zone=${ZONE}
run_date=${RUN_DATE}
run_id=${RUN_ID}
timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
  fi

  # Ensure all workspace outputs/logs are uploaded to GCS before self-deletion
  if [ -d /workspace/outputs ] && [ -n "${GCS_BUCKET:-}" ] && [ -n "${RUN_DATE:-}" ] && [ -n "${RUN_ID:-}" ]; then
    echo "Syncing final /workspace/outputs/ to GCS..."
    gsutil -m rsync -r /workspace/outputs/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/" || true
    
    # Explicit fallback for startup log to ensure we see why it failed
    if [ -f /workspace/outputs/startup.log ]; then
      gsutil cp /workspace/outputs/startup.log "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/startup.log" || true
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
echo "🚀 PredSea VM Startup Script Initialized"
echo "Project ID: ${PROJECT_ID}"
echo "Instance: ${NAME} in zone ${ZONE}"
echo "Execution Mode: ${EXECUTION_MODE}"
echo "Target Date/Run: ${RUN_DATE} / ${RUN_ID}"
echo "Forecast horizon: ${FORECAST_HOURS}h (${RUN_DATE}_00:00:00 through ${END_DATE})"
echo "============================================="

# 2. Setup folders
mkdir -p /workspace/inputs
mkdir -p /workspace/outputs
mkdir -p /workspace/inputs/static
mkdir -p /workspace/bin
mkdir -p /workspace/outputs/wrf
mkdir -p /workspace/outputs/roms
mkdir -p /workspace/outputs/swan

# Redirect all output to a log file as well as stdout for debugging
exec > >(tee -a /workspace/outputs/startup.log) 2>&1

# Download forcing data if available
echo "Downloading atmospheric boundary conditions from GCS..."
gsutil -m rsync -r "gs://${GCS_BUCKET}/forcing/ecmwf/${RUN_DATE}/" /workspace/inputs/ || echo "⚠️ Warning: Atmospheric boundary forcing not found."

echo "Downloading oceanic boundary conditions from GCS..."
gsutil -m rsync -r "gs://${GCS_BUCKET}/forcing/cmems/${RUN_DATE}/" /workspace/inputs/ || echo "⚠️ Warning: Oceanic boundary forcing not found."

# 3. Branch based on execution-mode
if [ "${EXECUTION_MODE}" = "container" ]; then
  # --------------------------------------------------
  # CONTAINER-BASED WORKFLOW (Docker)
  # --------------------------------------------------
  echo "🏃 Running Container-based execution flow..."

  # Install Docker if not already installed
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

  # Pull WRF/ROMS model image
  echo "Pulling model container image: ${DOCKER_IMAGE}"
  docker pull "${DOCKER_IMAGE}"

  # Download WPS_GEOG static geography dataset from high-performance computing bucket
  echo "Downloading WPS_GEOG static geography dataset..."
  mkdir -p /workspace/WPS_GEOG
  gsutil -m rsync -r gs://predsea-hpc-outputs/WPS_GEOG/ /workspace/WPS_GEOG/

  # Create safety symlinks for missing high-resolution datasets to avoid geogrid crashes.
  # Using relative links so they resolve correctly inside the docker container mount (/opt/WPS_GEOG).
  ln -sfn soiltype_top_5m /workspace/WPS_GEOG/soiltype_top_30s
  ln -sfn soiltype_bot_5m /workspace/WPS_GEOG/soiltype_bot_30s
  ln -sfn modis_landuse_20class_30s_with_lakes /workspace/WPS_GEOG/modis_landuse_21class_30s
  ln -sfn greenfrac_fpar_modis_5m /workspace/WPS_GEOG/greenfrac_fpar_modis
  ln -sfn greenfrac_fpar_modis_5m /workspace/WPS_GEOG/greenfrac_fpar_modis_30s
  ln -sfn lai_modis_10m /workspace/WPS_GEOG/lai_modis
  ln -sfn lai_modis_10m /workspace/WPS_GEOG/lai_modis_30s
  ln -sfn orogwd_1deg /workspace/WPS_GEOG/orogwd_10m
  ln -sfn orogwd_1deg /workspace/WPS_GEOG/orogwd_20m


  # Run model simulation inside the container
  echo "Executing model simulation in container..."
  set +e

  # Check if a pre-generated namelist.wps is present in the downloaded forcing inputs
  DOCKER_MOUNT_OPTS=""
  if [ -f /workspace/inputs/namelist.wps ]; then
    echo "Using pre-generated namelist.wps from forcing..."
    cp /workspace/inputs/namelist.wps /workspace/namelist.wps
    DOCKER_MOUNT_OPTS="${DOCKER_MOUNT_OPTS} -v /workspace/namelist.wps:/workspace/namelist.wps"
  fi

  if [ -f /workspace/inputs/run_pipeline.sh ]; then
    echo "Using updated run_pipeline.sh from forcing to bypass image rebuild..."
    cp /workspace/inputs/run_pipeline.sh /workspace/run_pipeline.sh
    chmod +x /workspace/run_pipeline.sh
    DOCKER_MOUNT_OPTS="${DOCKER_MOUNT_OPTS} -v /workspace/run_pipeline.sh:/opt/predsea/run_pipeline.sh"
  fi

  if [ -f /workspace/inputs/setup_domain.py ]; then
    echo "Using updated setup_domain.py from forcing to bypass image rebuild..."
    cp /workspace/inputs/setup_domain.py /workspace/setup_domain.py
    DOCKER_MOUNT_OPTS="${DOCKER_MOUNT_OPTS} -v /workspace/setup_domain.py:/opt/predsea/setup_domain.py"
  fi

  docker run --rm \
    --network=host \
    --shm-size=8gb \
    -v /workspace/inputs:/data \
    -v /workspace/outputs:/workspace/run \
    -v /workspace/WPS_GEOG:/opt/WPS_GEOG \
    ${DOCKER_MOUNT_OPTS:-} \
    -e START_DATE="${RUN_DATE}_00:00:00" \
    -e END_DATE="${END_DATE}" \
    -e MPI_PROCS="${PREDSEA_WRF_MPI_PROCS:-64}" \
    -e MPI_NPROC_X="${PREDSEA_WRF_MPI_NPROC_X:-8}" \
    -e MPI_NPROC_Y="${PREDSEA_WRF_MPI_NPROC_Y:-8}" \
    "${DOCKER_IMAGE}" \
    /opt/predsea/run_pipeline.sh 2>&1 | tee /workspace/outputs/docker_run.log
  DOCKER_EXIT_CODE=${PIPESTATUS[0]}
  set -e

  if [ $DOCKER_EXIT_CODE -ne 0 ]; then
    echo "❌ Error: Docker container failed with exit code $DOCKER_EXIT_CODE."
    exit $DOCKER_EXIT_CODE
  fi

else
  # --------------------------------------------------
  # BARE-METAL WORKFLOW (Native Parallel Executables)
  # --------------------------------------------------
  echo "🏃 Running Bare-metal parallel execution flow..."

  # Install MPI, NetCDF runtime and build dependencies
  echo "Installing MPI and NetCDF dependencies..."
  apt-get update
  apt-get install -y mpich libopenmpi-dev libnetcdf-dev libnetcdff-dev python3 python3-netcdf4 python3-pip

  # Download compiled binaries from GCS
  echo "Downloading compiled binaries from GCS..."
  gsutil cp "gs://predsea-hpc-outputs/binaries/wrf.exe" /workspace/bin/wrf.exe || echo "⚠️ Warning: wrf.exe not found in GCS."
  gsutil cp "gs://predsea-hpc-outputs/binaries/real.exe" /workspace/bin/real.exe || echo "⚠️ Warning: real.exe not found in GCS."
  gsutil cp "gs://predsea-hpc-outputs/binaries/croco.exe" /workspace/bin/croco.exe || echo "⚠️ Warning: croco.exe not found in GCS."
  gsutil cp "gs://predsea-hpc-outputs/binaries/swan.exe" /workspace/bin/swan.exe || echo "⚠️ Warning: swan.exe not found in GCS."
  gsutil cp "gs://predsea-hpc-outputs/binaries/setup_domain.py" /workspace/bin/setup_domain.py || echo "⚠️ Warning: setup_domain.py not found in GCS."

  if [ -f /workspace/bin/wrf.exe ] || [ -f /workspace/bin/real.exe ] || [ -f /workspace/bin/croco.exe ] || [ -f /workspace/bin/swan.exe ]; then
    chmod +x /workspace/bin/*.exe || true
  fi

  echo "Downloading static files from GCS..."
  gsutil -m rsync -r "gs://predsea-hpc-outputs/static/" /workspace/inputs/static/ || echo "⚠️ Warning: Static files not found in GCS."

  # Copy static tables and configuration to run directories
  cp /workspace/inputs/static/* /workspace/outputs/wrf/ || true
  cp /workspace/inputs/static/namelist.input /workspace/outputs/wrf/namelist.input || echo "⚠️ namelist.input template copy failed"

  # Patch namelist.input dates
  if [ -f /workspace/outputs/wrf/namelist.input ] && [ -f /workspace/bin/setup_domain.py ]; then
    echo "Patching namelist.input dates..."
    python3 /workspace/bin/setup_domain.py \
      --start-date "${RUN_DATE}_00:00:00" \
      --end-date "${END_DATE}" \
      --patch-namelist-input /workspace/outputs/wrf/namelist.input || true
  fi

  CORES=$(nproc)
  echo "System has ${CORES} cores available for parallel execution."

  # Step A: WRF (dynamic parallel cores)
  echo "============================================="
  echo "🏃 Running Step A: WRF (${CORES}-core parallel)"
  echo "============================================="
  cd /workspace/outputs/wrf
  if [ -f /workspace/bin/real.exe ]; then
    echo "Running real.exe..."
    mpirun -np "${CORES}" /workspace/bin/real.exe 2>&1 | tee real.log || true
  fi
  if [ -f /workspace/bin/wrf.exe ]; then
    echo "Running wrf.exe..."
    mpirun -np "${CORES}" /workspace/bin/wrf.exe 2>&1 | tee wrf.log || true
  fi

  # Step B: CROCO/ROMS (dynamic parallel cores)
  CROCO_CORES=$((CORES / 2 > 16 ? CORES / 2 : 16))
  echo "============================================="
  echo "🏃 Running Step B: CROCO/ROMS (${CROCO_CORES}-core parallel)"
  echo "============================================="
  cd /workspace/outputs/roms
  if [ -f /workspace/bin/croco.exe ]; then
    echo "Running croco.exe..."
    mpirun -np "${CROCO_CORES}" /workspace/bin/croco.exe 2>&1 | tee croco.log || true
  fi

  # Step C: SWAN (dynamic parallel cores)
  SWAN_CORES=$((CORES / 4 > 8 ? CORES / 4 : 8))
  echo "============================================="
  echo "🏃 Running Step C: SWAN (${SWAN_CORES}-core parallel)"
  echo "============================================="
  cd /workspace/outputs/swan
  if [ -f /workspace/bin/swan.exe ]; then
    echo "Running swan.exe..."
    mpirun -np "${SWAN_CORES}" /workspace/bin/swan.exe 2>&1 | tee swan.log || true
  fi
fi

# A valid hourly run includes both hour zero and the final forecast hour.
EXPECTED_WRF_TIMESTAMPS=$((FORECAST_HOURS + 1))
WRF_DOMAIN="d02"
WRF_OUTPUT_COUNT=$(find /workspace/outputs -type f -name "wrfout_${WRF_DOMAIN}_*" | wc -l)
if [ "${WRF_OUTPUT_COUNT}" -ne "${EXPECTED_WRF_TIMESTAMPS}" ]; then
  echo "❌ WRF output coverage is incomplete: expected ${EXPECTED_WRF_TIMESTAMPS} hourly ${WRF_DOMAIN} files for ${FORECAST_HOURS}h, found ${WRF_OUTPUT_COUNT}."
  exit 99
fi
echo "✅ WRF output coverage complete: ${WRF_OUTPUT_COUNT}/${EXPECTED_WRF_TIMESTAMPS} hourly ${WRF_DOMAIN} files."

# 4. Sync the results directly to GCS predictions bucket
echo "Syncing model outputs directly to GCS..."
if [ -d /workspace/outputs/wrf ]; then
  gsutil -m rsync -r /workspace/outputs/wrf/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/wrf/" || true
fi
if [ -d /workspace/outputs/roms ]; then
  gsutil -m rsync -r /workspace/outputs/roms/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/roms/" || true
fi
if [ -d /workspace/outputs/swan ]; then
  gsutil -m rsync -r /workspace/outputs/swan/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/swan/" || true
fi

# 5. Upload standard outputs back to GCS (for compatibility/logging)
echo "Uploading generic outputs and logs to GCS..."
gsutil -m rsync -r /workspace/outputs/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/" || true

# 6. Write and upload SUCCESS marker file to signal successful run completion
echo "Uploading SUCCESS marker file to GCS..."
echo "SUCCESS" > /tmp/SUCCESS
gsutil cp /tmp/SUCCESS "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/SUCCESS"

echo "============================================="
echo "🎉 Simulation pipeline complete!"
echo "============================================="
