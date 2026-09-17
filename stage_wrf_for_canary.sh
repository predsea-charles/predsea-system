#!/usr/bin/env bash
# stage_wrf_for_canary.sh (v4) — copy ONLY the required wrfout_d02_* hourly
# files from an existing SUCCEEDED WRF run into a canary run_id's expected
# path, so the CROCO runner finds forcing data without regenerating WRF and
# without duplicating the entire WRF work directory.
#
# v4 fix (per agent finding): v3 copied the ENTIRE wrf/ prefix recursively —
# 708 objects / ~93.6 GB for a full run, when a short canary only needs
# (forecast_hours + 1) hourly wrfout_d02_* files (e.g. 4 files for a 3h
# canary: hours 0,1,2,3). This version lists, filters to that exact pattern
# and count, and copies only those files.
#
# IMPORTANT — verify the file-count assumption before relying on it: this
# script assumes CROCO's boundary/initial forcing needs exactly
# (forecast_hours + 1) hourly wrfout_d02_* files. That matches what was
# found during investigation, but if run_marine_simulation.py or
# prepare_croco_in.py expects a different count, pattern, or additional
# domains (d01/d03), update --file-pattern / --file-count accordingly rather
# than assuming this default is universally correct.

set -euo pipefail

S3_BUCKET=""
SOURCE_RUN_DATE=""
SOURCE_RUN_ID=""
CANARY_RUN_DATE=""
CANARY_RUN_ID=""
FORECAST_HOURS=""
FILE_COUNT=""
FILE_PATTERN="wrfout_d02_"
REGION_AWS="eu-west-1"
DRY_RUN="false"

usage() {
  cat <<EOF
Usage: $0 --s3-bucket <bucket> --source-run-date <YYYY-MM-DD> \\
           --source-run-id <existing-succeeded-run-id> \\
           --canary-run-date <YYYY-MM-DD> --canary-run-id <new-canary-run-id> \\
           --forecast-hours <n> [--file-pattern <prefix>] [--file-count <n>] \\
           [--region-aws <aws-region>] [--dry-run]

Copies exactly (forecast_hours + 1) files matching --file-pattern
(default: "wrfout_d02_"), sorted, earliest first — NOT the entire wrf/
directory. Override --file-count directly if the +1 assumption is wrong for
your case.

Example:
  $0 --s3-bucket predsea-daily-outputs \\
     --source-run-date 2026-09-12 --source-run-id 2026-09-12T0000Z-72h \\
     --canary-run-date 2026-09-13 --canary-run-id 2026-09-13T0000Z-canary-dt90 \\
     --forecast-hours 3 --dry-run

Always run with --dry-run first and read the exact file list before running
for real.
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --s3-bucket) S3_BUCKET="$2"; shift 2 ;;
    --source-run-date) SOURCE_RUN_DATE="$2"; shift 2 ;;
    --source-run-id) SOURCE_RUN_ID="$2"; shift 2 ;;
    --canary-run-date) CANARY_RUN_DATE="$2"; shift 2 ;;
    --canary-run-id) CANARY_RUN_ID="$2"; shift 2 ;;
    --forecast-hours) FORECAST_HOURS="$2"; shift 2 ;;
    --file-count) FILE_COUNT="$2"; shift 2 ;;
    --file-pattern) FILE_PATTERN="$2"; shift 2 ;;
    --region-aws) REGION_AWS="$2"; shift 2 ;;
    --dry-run) DRY_RUN="true"; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

if [[ -z "$S3_BUCKET" || -z "$SOURCE_RUN_DATE" || -z "$SOURCE_RUN_ID" || -z "$CANARY_RUN_DATE" || -z "$CANARY_RUN_ID" || -z "$FORECAST_HOURS" ]]; then
  echo "ERROR: --s3-bucket, --source-run-date, --source-run-id, --canary-run-date, --canary-run-id, --forecast-hours are all required."
  usage
fi

if [[ "$SOURCE_RUN_ID" == "$CANARY_RUN_ID" ]]; then
  echo "ERROR: --source-run-id and --canary-run-id are identical. Refusing."
  exit 1
fi

if [[ -z "$FILE_COUNT" ]]; then
  FILE_COUNT=$(( FORECAST_HOURS + 1 ))
  echo "NOTE: --file-count not given, defaulting to forecast_hours+1 = $FILE_COUNT."
  echo "This assumption is unverified against run_marine_simulation.py — pass"
  echo "--file-count explicitly if you know the real requirement differs."
fi

SRC_PREFIX="predictions/${SOURCE_RUN_DATE}/runs/${SOURCE_RUN_ID}/wrf/"
DST_PREFIX="predictions/${CANARY_RUN_DATE}/runs/${CANARY_RUN_ID}/wrf/"
SRC_BASE="s3://${S3_BUCKET}/${SRC_PREFIX}"
DST_BASE="s3://${S3_BUCKET}/${DST_PREFIX}"

echo "----------------------------------------------------------------------"
echo "Staging WRF output for canary run (selective copy, NOT full recursive)"
echo "  source prefix: $SRC_BASE"
echo "  dest prefix:   $DST_BASE"
echo "  file pattern:  ${FILE_PATTERN}*"
echo "  file count:    $FILE_COUNT"
echo "----------------------------------------------------------------------"

# List matching files, sorted, take the first FILE_COUNT, and require they
# are non-empty (size > 0) — a zero-byte file would look "present" but
# contain no usable forcing data.
MATCHING_LINES=()
while IFS= read -r line; do
  [[ -n "$line" ]] && MATCHING_LINES+=("$line")
done < <(
  aws s3 ls "$SRC_BASE" --recursive --region "$REGION_AWS" \
    | awk -v pat="$FILE_PATTERN" '{ n=split($0,a,"/"); fname=a[n]; if (index(fname, pat)==1 && $3+0 > 0) print $0 }' \
    | sort -k1,1 -k2,2 \
    | head -n "$FILE_COUNT"
)

FOUND_COUNT=${#MATCHING_LINES[@]}
if (( FOUND_COUNT < FILE_COUNT )); then
  echo "ERROR: found only $FOUND_COUNT non-empty file(s) matching '${FILE_PATTERN}*' "
  echo "at the source, but $FILE_COUNT are required. Refusing to stage a"
  echo "partial/incomplete forcing set."
  echo ""
  echo "Matches found:"
  printf '  %s\n' "${MATCHING_LINES[@]}"
  exit 1
fi

echo "Found $FOUND_COUNT matching non-empty file(s):"
printf '  %s\n' "${MATCHING_LINES[@]}"

if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  echo "[DRY RUN] Would copy exactly these $FILE_COUNT file(s) from source to dest."
  echo "Re-run without --dry-run to actually copy."
  exit 0
fi

echo ""
echo "Copying $FILE_COUNT file(s) (server-side, same bucket/region)..."
COPIED=0
for line in "${MATCHING_LINES[@]}"; do
  fname=$(echo "$line" | awk '{ n=split($0,a,"/"); print a[n] }')
  aws s3 cp "${SRC_BASE}${fname}" "${DST_BASE}${fname}" --region "$REGION_AWS"
  COPIED=$((COPIED + 1))
done

echo ""
echo "Verifying destination..."
DST_COUNT=$(aws s3 ls "$DST_BASE" --recursive --region "$REGION_AWS" \
  | awk -v pat="$FILE_PATTERN" '{ n=split($0,a,"/"); fname=a[n]; if (index(fname, pat)==1 && $3+0 > 0) print $0 }' \
  | wc -l | tr -d ' ')

if [[ "$DST_COUNT" != "$FILE_COUNT" ]]; then
  echo "ERROR: expected $FILE_COUNT file(s) at destination, found $DST_COUNT."
  echo "Do not proceed to submit the CROCO canary job until this is resolved."
  exit 1
fi

echo "Destination has exactly $FILE_COUNT matching non-empty file(s). Staging complete."
echo ""
echo "This canary run_id ('${CANARY_RUN_ID}') can now be submitted with"
echo "submit_canary.sh — make sure --run-id-prefix there resolves to the"
echo "exact same run_id as used here (see README for how RUN_ID is built)."
