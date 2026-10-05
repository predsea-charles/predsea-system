#!/usr/bin/env bash
# compile_ww3_grid_2km.sh
#
# One-shot script: compiles mod_def.ww3 for the western_mediterranean_2km grid
# by running `ww3_grid` inside the WW3 Docker container, then uploads the result
# to S3 so every production run can stage it without recompiling.
#
# Run this ONCE (or whenever the grid definition changes) before the first
# production run.  Idempotent — re-running just overwrites the S3 objects.
#
# Usage:
#   ./scripts/compile_ww3_grid_2km.sh [OPTIONS]
#
# Options:
#   --image  URI    Full ECR image URI for the WW3 image (default: auto-detect
#                   from ECR using AWS_ACCOUNT_ID + AWS_REGION).
#   --bucket NAME   S3 bucket (default: predsea-daily-outputs).
#   --region CODE   AWS region (default: eu-west-1).
#   --dry-run       Build and run ww3_grid locally; skip the S3 upload.
#
# Requirements:
#   docker, aws CLI, jq

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
BUCKET="${BUCKET:-predsea-daily-outputs}"
AWS_REGION="${AWS_REGION:-eu-west-1}"
IMAGE_URI=""
DRY_RUN=false
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GRID_DIR="${REPO_ROOT}/simulation/marine/ww3/grids/western_mediterranean_2km"
S3_PREFIX="static/native-marine/western_mediterranean_2km/ww3-grid"

# ── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)  IMAGE_URI="$2";  shift 2 ;;
    --bucket) BUCKET="$2";     shift 2 ;;
    --region) AWS_REGION="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true;   shift   ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Resolve WW3 image ────────────────────────────────────────────────────────
if [[ -z "$IMAGE_URI" ]]; then
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/predsea-ww3:latest"
  echo "Auto-detected image: ${IMAGE_URI}"
fi

# ── ECR login ────────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "false" ]]; then
  REGISTRY=$(echo "$IMAGE_URI" | cut -d/ -f1)
  echo "Logging in to ECR (${REGISTRY})..."
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$REGISTRY"
fi

# ── Validate grid files ───────────────────────────────────────────────────────
echo "Checking grid files in: ${GRID_DIR}"
for f in ww3_grid.nml depth.inp namelists.nml ST4TABUHF2.bin; do
  if [[ ! -f "${GRID_DIR}/${f}" ]]; then
    echo "ERROR: missing required file: ${GRID_DIR}/${f}" >&2
    exit 1
  fi
done
echo "  ✅ all required grid files present"

# ── Scratch directory ────────────────────────────────────────────────────────
# Use REPO_ROOT for the scratch dir — /tmp on macOS is a symlink to /private/tmp
# and Docker Desktop does not reliably bind-mount through that symlink.
# A directory under the repo (which is under /Users/…) is always shared correctly.
WORK_DIR=$(mktemp -d "${REPO_ROOT}/.ww3_grid_compile.XXXXXX")
trap 'rm -rf "${WORK_DIR}"' EXIT
echo "Working directory: ${WORK_DIR}"

# Copy grid inputs into scratch (ww3_grid writes mod_def.ww3 to cwd)
cp "${GRID_DIR}/ww3_grid.nml"   "${WORK_DIR}/"
cp "${GRID_DIR}/depth.inp"       "${WORK_DIR}/"
cp "${GRID_DIR}/namelists.nml"   "${WORK_DIR}/"
cp "${GRID_DIR}/ST4TABUHF2.bin"  "${WORK_DIR}/"

# ── Run ww3_grid in Docker ────────────────────────────────────────────────────
echo ""
echo "Running ww3_grid inside Docker container..."
echo "  Image  : ${IMAGE_URI}"
echo "  Grid   : western_mediterranean_2km (NX=1110, NY=528, ~2km)"
echo ""

docker run --rm \
  --name predsea-ww3-grid-compile \
  -v "${WORK_DIR}:/workspace" \
  -w /workspace \
  --entrypoint /bin/bash \
  "${IMAGE_URI}" \
  -c "
    set -euo pipefail
    echo '[debug] Working directory: '\$(pwd)
    echo '[debug] Files present:'
    ls -la
    echo '[debug] ww3_grid binary location:'
    which ww3_grid || true
    echo '[debug] ww3_grid.nml exists: '\$([ -f ww3_grid.nml ] && echo yes || echo no)
    echo '[debug] ww3_grid.inp exists: '\$([ -f ww3_grid.inp ] && echo yes || echo no)
    # Provide both filename variants (some builds use .inp, some use .nml)
    [ -f ww3_grid.nml ] && cp ww3_grid.nml ww3_grid.inp
    echo '[ww3_grid] Starting grid compilation...'
    ww3_grid 2>&1 | tee ww3_grid.log
    echo '[ww3_grid] Done.'
    if [[ ! -f mod_def.ww3 ]]; then
      echo 'ERROR: mod_def.ww3 was not produced!' >&2
      exit 1
    fi
    ls -lh mod_def.ww3
  "

# ── Verify output ─────────────────────────────────────────────────────────────
if [[ ! -f "${WORK_DIR}/mod_def.ww3" ]]; then
  echo "ERROR: mod_def.ww3 not found in ${WORK_DIR} after container run." >&2
  exit 1
fi

MOD_DEF_SIZE=$(du -sh "${WORK_DIR}/mod_def.ww3" | cut -f1)
echo "  ✅ mod_def.ww3 produced (${MOD_DEF_SIZE})"

# ── Upload to S3 ───────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  echo "DRY-RUN: would upload to:"
  echo "  s3://${BUCKET}/${S3_PREFIX}/mod_def.ww3"
  echo "  s3://${BUCKET}/${S3_PREFIX}/ST4TABUHF2.bin"
  echo ""
  echo "mod_def.ww3 is at: ${WORK_DIR}/mod_def.ww3"
else
  echo ""
  echo "Uploading to s3://${BUCKET}/${S3_PREFIX}/ ..."

  aws s3 cp "${WORK_DIR}/mod_def.ww3" \
    "s3://${BUCKET}/${S3_PREFIX}/mod_def.ww3" \
    --region "$AWS_REGION"
  echo "  ✅ uploaded mod_def.ww3"

  # Also stage ST4TABUHF2.bin alongside mod_def.ww3 so the runner can
  # download both from a single S3 prefix without knowing the repo path.
  aws s3 cp "${GRID_DIR}/ST4TABUHF2.bin" \
    "s3://${BUCKET}/${S3_PREFIX}/ST4TABUHF2.bin" \
    --region "$AWS_REGION"
  echo "  ✅ uploaded ST4TABUHF2.bin"

  echo ""
  echo "Verifying S3 objects:"
  aws s3 ls "s3://${BUCKET}/${S3_PREFIX}/" --region "$AWS_REGION"
fi

echo ""
echo "✅ Done. Production runs can now stage from:"
echo "   s3://${BUCKET}/${S3_PREFIX}/"
