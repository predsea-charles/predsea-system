#!/usr/bin/env bash
# setup_wps_geog_s3.sh
#
# Downloads WPS geographic static data from NCAR and uploads it to S3.
# Run this ONCE before the first WRF production run.
#
# Total download: ~5-6 GB  |  Upload to S3: same
# Typical wall time: 20-40 min depending on your connection.
#
# Usage:
#   ./scripts/setup_wps_geog_s3.sh [--bucket predsea-daily-outputs] [--region eu-west-1]

set -euo pipefail

BUCKET="${BUCKET:-predsea-daily-outputs}"
AWS_REGION="${AWS_REGION:-eu-west-1}"
NCAR_BASE="https://www2.mmm.ucar.edu/wrf/src/wps_files"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket)  BUCKET="$2";     shift 2 ;;
    --region)  AWS_REGION="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

S3_PREFIX="s3://${BUCKET}/static/wrf/WPS_GEOG"

WORK_DIR=$(mktemp -d /tmp/WPS_GEOG_setup.XXXXXX)
trap 'echo "Cleaning up ${WORK_DIR}..."; rm -rf "${WORK_DIR}"' EXIT
WPS_GEOG="${WORK_DIR}/WPS_GEOG"
mkdir -p "${WPS_GEOG}"

echo "=================================================="
echo "WPS_GEOG setup: download from NCAR → upload to S3"
echo "  Bucket : ${BUCKET}"
echo "  Prefix : ${S3_PREFIX}/"
echo "  Work   : ${WORK_DIR}"
echo "=================================================="
echo ""

download_and_extract() {
  local filename="$1"
  local url="${NCAR_BASE}/${filename}"
  local dest="${WORK_DIR}/${filename}"

  echo "⬇️  Downloading ${filename}..."
  curl -L --progress-bar -o "${dest}" "${url}"
  echo "📦 Extracting ${filename}..."

  case "${filename}" in
    *.tar.gz)  tar -xzf "${dest}" -C "${WPS_GEOG}" --strip-components=1 2>/dev/null || \
                 tar -xzf "${dest}" -C "${WPS_GEOG}" ;;
    *.tar.bz2) tar -xjf "${dest}" -C "${WPS_GEOG}" --strip-components=1 2>/dev/null || \
                 tar -xjf "${dest}" -C "${WPS_GEOG}" ;;
  esac
  rm -f "${dest}"
  echo "  ✅ Done"
}

# ── Downloads ─────────────────────────────────────────────────────────────────
# 1. Mandatory low-resolution datasets (~1.8 GB)
#    Includes: albedo_ncep, greenfrac, landuse_30s, maxsnowalb, orogwd_2deg,
#              slp, soiltype_bot_30s, soiltype_top_30s, topo_30s, etc.
download_and_extract "geog_low_res_mandatory.tar.gz"

# 2. GMTED2010 terrain height at 30 arc-second (~2 GB)
#    Provides topo_gmted2010_30s/ — required by GEOGRID.TBL for HGT_M in WPS 4+.
#    (The older topo_30s GTOPO30 dataset is included in geog_low_res_mandatory
#     but newer GEOGRID.TBL defaults point to GMTED2010 for the 30s resolution.)
download_and_extract "topo_gmted2010_30s.tar.bz2"

# 3. MODIS land use 20-class 30 arc-second with lakes (~3.3 GB)
#    Provides the modis_landuse_20class_30s_with_lakes/ directory used by
#    geog_data_res = 'modis_landuse_20class_30s_with_lakes+default'
download_and_extract "modis_landuse_20class_30s_with_lakes.tar.bz2"

# 3. MODIS greenfrac + LAI at 5m (needed for Mediterranean runs)
#    The GCE pipeline symlinked these; downloading the actual data is more robust.
download_and_extract "greenfrac_fpar_modis_5m.tar.bz2"
download_and_extract "lai_modis_10m.tar.bz2"

# ── Symlinks (mirror GCE vm_startup.sh for compatibility) ─────────────────────
echo ""
echo "Creating compatibility symlinks..."
cd "${WPS_GEOG}"

# WPS GEOGRID.TBL may reference these alternative names
[ -d soiltype_top_5m ]  && ln -sfn soiltype_top_5m  soiltype_top_30s  && echo "  linked soiltype_top_30s"
[ -d soiltype_bot_5m ]  && ln -sfn soiltype_bot_5m  soiltype_bot_30s  && echo "  linked soiltype_bot_30s"
[ -d greenfrac_fpar_modis_5m ] && {
  ln -sfn greenfrac_fpar_modis_5m greenfrac_fpar_modis     && echo "  linked greenfrac_fpar_modis"
  ln -sfn greenfrac_fpar_modis_5m greenfrac_fpar_modis_30s && echo "  linked greenfrac_fpar_modis_30s"
}
[ -d lai_modis_10m ] && {
  ln -sfn lai_modis_10m lai_modis     && echo "  linked lai_modis"
  ln -sfn lai_modis_10m lai_modis_30s && echo "  linked lai_modis_30s"
}
[ -d modis_landuse_20class_30s_with_lakes ] && \
  ln -sfn modis_landuse_20class_30s_with_lakes modis_landuse_21class_30s && \
  echo "  linked modis_landuse_21class_30s"
[ -d orogwd_1deg ] && {
  ln -sfn orogwd_1deg orogwd_10m && echo "  linked orogwd_10m"
  ln -sfn orogwd_1deg orogwd_20m && echo "  linked orogwd_20m"
}

cd - >/dev/null

# ── Validate ──────────────────────────────────────────────────────────────────
echo ""
echo "Validating WPS_GEOG structure..."
REQUIRED_DIRS=(
  "modis_landuse_20class_30s_with_lakes"
  "topo_gmted2010_30s"
  "topo_30s"
  "soiltype_top_30s"
  "soiltype_bot_30s"
  "greenfrac_fpar_modis"
  "lai_modis"
  "albedo_ncep"
  "maxsnowalb"
)
MISSING=()
for dir in "${REQUIRED_DIRS[@]}"; do
  if [ ! -d "${WPS_GEOG}/${dir}" ] && [ ! -L "${WPS_GEOG}/${dir}" ]; then
    MISSING+=("${dir}")
  fi
done
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "⚠️  Missing expected directories: ${MISSING[*]}"
  echo "    The upload will continue but WRF may fail at geogrid."
else
  echo "  ✅ All required directories present"
fi

TOTAL_SIZE=$(du -sh "${WPS_GEOG}" | cut -f1)
echo "  Total size: ${TOTAL_SIZE}"

# ── Upload to S3 ──────────────────────────────────────────────────────────────
echo ""
echo "Uploading to ${S3_PREFIX}/ ..."
echo "(This may take 10-30 min depending on your upload speed)"
aws s3 sync "${WPS_GEOG}/" "${S3_PREFIX}/" \
  --region "${AWS_REGION}" \
  --only-show-errors

echo ""
echo "Verifying upload..."
COUNT=$(aws s3 ls "${S3_PREFIX}/" --recursive --region "${AWS_REGION}" | wc -l | tr -d ' ')
echo "  ✅ ${COUNT} objects in ${S3_PREFIX}/"

echo ""
echo "✅ Done. WPS_GEOG is staged and ready for WRF runs."
echo "   geog_data_res = 'modis_landuse_20class_30s_with_lakes+default'"
