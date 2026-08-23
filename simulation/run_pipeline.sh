#!/usr/bin/env bash
set -euo pipefail

WPS_DIR="${WPS_DIR:-/opt/WPS}"
WRF_DIR="${WRF_DIR:-/opt/WRF}"
PREDSEA_BIN="${PREDSEA_BIN:-/opt/predsea/bin}"
GRIB_DIR="${GRIB_DIR:-/data}"
RUN_DIR="${RUN_DIR:-/workspace/run}"
NAMELIST_WPS="${NAMELIST_WPS:-/workspace/namelist.wps}"
if [[ -f "/data/Vtable.ECMWF_grib2" ]]; then
  Vtable="/data/Vtable.ECMWF_grib2"
elif [[ -f "/data/Vtable.ECMWF" ]]; then
  Vtable="/data/Vtable.ECMWF"
else
  Vtable="${WPS_DIR}/ungrib/Variable_Tables/Vtable.ECMWF"
fi
MPI_PROCS="${MPI_PROCS:-64}"
MPI_NPROC_X="${MPI_NPROC_X:-8}"
MPI_NPROC_Y="${MPI_NPROC_Y:-8}"
read -r -a MPI_EXTRA_ARGS_ARRAY <<< "${MPI_EXTRA_ARGS:-}"
WPS_STAGE_TIMEOUT_SECONDS="${WPS_STAGE_TIMEOUT_SECONDS:-1800}"

if (( MPI_PROCS != MPI_NPROC_X * MPI_NPROC_Y )); then
  echo "❌ MPI_PROCS=${MPI_PROCS} must equal MPI_NPROC_X*MPI_NPROC_Y (${MPI_NPROC_X}*${MPI_NPROC_Y})."
  exit 96
fi

mkdir -p "${RUN_DIR}"
cd "${RUN_DIR}"

if [[ ! -f "${NAMELIST_WPS}" ]]; then
  python3 /opt/predsea/setup_domain.py \
    --output "${NAMELIST_WPS}" \
    --start-date "${START_DATE:-2026-05-04_00:00:00}" \
    --end-date "${END_DATE:-2026-05-05_00:00:00}"
fi

cp "${NAMELIST_WPS}" "${WPS_DIR}/namelist.wps"
cd "${WPS_DIR}"

# Ensure required WPS output directories exist
mkdir -p ./geo_em
mkdir -p ./met_em

ln -sf "${Vtable}" Vtable
if [[ -f "./metgrid/METGRID.TBL.ECMWF" ]]; then
  echo "Using METGRID.TBL.ECMWF..."
  (cd metgrid && ln -sf METGRID.TBL.ECMWF METGRID.TBL)
  ls -l metgrid/METGRID.TBL
fi

run_wps_stage() {
  local stage="$1"
  local exe="${PREDSEA_BIN}/${stage}.exe"
  local stdout_log="${stage}_stdout.log"
  local native_log="${stage}.log"

  echo "Running ${stage}..."
  set +e
  timeout --signal=TERM --kill-after=30s "${WPS_STAGE_TIMEOUT_SECONDS}" \
    "${exe}" > "${stdout_log}" 2>&1
  local rc=$?
  set -e

  cp "${native_log}" "${stdout_log}" "${RUN_DIR}/" || true
  if [[ ${rc} -ne 0 ]]; then
    echo "❌ ${stage}.exe failed with exit code ${rc}."
    echo "Last lines from ${stdout_log}:"
    tail -n 80 "${stdout_log}" || true
    if [[ -f "${native_log}" ]]; then
      echo "Last lines from ${native_log}:"
      tail -n 80 "${native_log}" || true
    fi
    exit "${rc}"
  fi
}

# 3. Split GRIB input into one physical file per valid time. WPS 4.5 computes
# one hdate from the first message in each GRIBFILE and assumes every message
# in that file belongs to that time. A multi-time ECMWF file therefore
# collapses to its first (00Z) timestamp even when every forecast step is
# encoded correctly.
echo "Preparing one GRIB file per ECMWF valid time from ${GRIB_DIR}..."
if ls "${GRIB_DIR}"/ecmwf_*.grib2 1> /dev/null 2>&1; then
    COMBINED_GRIB="${RUN_DIR}/ecmwf_wps_combined_unsorted.grib2"
    SPLIT_GRIB_DIR="${RUN_DIR}/grib_by_valid_time"
    mkdir -p "${SPLIT_GRIB_DIR}"
    rm -f "${SPLIT_GRIB_DIR}"/ecmwf_*.grib2
    cat "${GRIB_DIR}"/ecmwf_*.grib2 > "${COMBINED_GRIB}"
    grib_copy "${COMBINED_GRIB}" \
      "${SPLIT_GRIB_DIR}/ecmwf_[validityDate]_[validityTime].grib2"

    mapfile -d '' -t WPS_GRIB_FILES < <(
      find "${SPLIT_GRIB_DIR}" -maxdepth 1 -type f \
        -name 'ecmwf_*.grib2' -print0 | sort -zV
    )
    if (( ${#WPS_GRIB_FILES[@]} < 2 )); then
      echo "❌ Error: GRIB split produced fewer than two valid-time files."
      exit 97
    fi
    echo "Prepared ${#WPS_GRIB_FILES[@]} chronologically ordered GRIB time files."
    ./link_grib.csh "${WPS_GRIB_FILES[@]}"
else
    echo "❌ Error: No GRIB files found in ${GRIB_DIR}"
    exit 1
fi

run_wps_stage ungrib

# Fail with an explicit missing-time report before metgrid emits a misleading
# mandatory-field error.
missing_intermediate_times=()
start_time="${START_DATE:-2026-05-04_00:00:00}"
end_time="${END_DATE:-2026-05-05_00:00:00}"
expected_epoch="$(date -u -d "${start_time/_/ } UTC" '+%s')"
end_epoch="$(date -u -d "${end_time/_/ } UTC" '+%s')"
while (( expected_epoch <= end_epoch )); do
  expected_time="$(date -u -d "@${expected_epoch}" '+%Y-%m-%d_%H:%M:%S')"
  intermediate="ECMWF:${expected_time:0:10}_${expected_time:11:2}"
  [[ -f "${intermediate}" ]] || missing_intermediate_times+=("${intermediate}")
  expected_epoch=$((expected_epoch + 3 * 60 * 60))
done
if (( ${#missing_intermediate_times[@]} > 0 )); then
  echo "❌ ungrib did not create all required WPS intermediate files."
  printf 'Missing: %s\n' "${missing_intermediate_times[@]}"
  exit 98
fi
echo "✅ ungrib created the complete WPS intermediate time sequence."

run_wps_stage geogrid
run_wps_stage metgrid

# Set MPI environment variables for container stability
export OMPI_MCA_btl_vader_single_copy_mechanism=none
export OMP_NUM_THREADS=1

# Re-enable strict error checking
set -e

cd "${RUN_DIR}"
cp "${WPS_DIR}"/met_em/met_em.d0*.nc .
cp "${WRF_DIR}/run"/* . || true
python3 /opt/predsea/setup_domain.py \
  --start-date "${START_DATE:-2026-05-04_00:00:00}" \
  --end-date "${END_DATE:-2026-05-05_00:00:00}" \
  --patch-namelist-input namelist.input
cp "${PREDSEA_BIN}/real.exe" .
cp "${PREDSEA_BIN}/wrf.exe" .

echo "Using explicit WRF MPI decomposition ${MPI_NPROC_X}x${MPI_NPROC_Y} (${MPI_PROCS} pure-MPI ranks)."

mpirun -np "${MPI_PROCS}" --oversubscribe --allow-run-as-root "${MPI_EXTRA_ARGS_ARRAY[@]}" "${PREDSEA_BIN}/real.exe"
mpirun -np "${MPI_PROCS}" --oversubscribe --allow-run-as-root "${MPI_EXTRA_ARGS_ARRAY[@]}" "${PREDSEA_BIN}/wrf.exe"

echo "WRF output files:"
ls -1 wrfout_d0*
