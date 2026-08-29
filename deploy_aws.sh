#!/usr/bin/env bash
set -Eeuo pipefail

AWS_REGION="${AWS_REGION:-eu-west-1}"
TF_DIR="${TF_DIR:-infra/aws}"
SOURCE_ZIP="$(mktemp -t predsea-aws-source.XXXXXX).zip"
trap 'rm -f "$SOURCE_ZIP"' EXIT

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v terraform >/dev/null || { echo "Terraform is required" >&2; exit 1; }
command -v zip >/dev/null || { echo "zip is required" >&2; exit 1; }
aws sts get-caller-identity >/dev/null

terraform -chdir="$TF_DIR" init
terraform -chdir="$TF_DIR" apply -var=create_api_service=false "$@"

BUCKET="$(terraform -chdir="$TF_DIR" output -raw bucket)"
BUILD_PROJECT="$(terraform -chdir="$TF_DIR" output -raw codebuild_project)"

zip -q -r "$SOURCE_ZIP" . \
  -x '.git/*' '.terraform/*' 'infra/aws/.terraform/*' '*.pyc' '*/__pycache__/*' \
     'predictions/*' 'observations/*' 'simulation/inputs/*' '*.grib2' '*.zip'
aws s3 cp "$SOURCE_ZIP" "s3://$BUCKET/codebuild-source/source.zip" --region "$AWS_REGION" --sse AES256

BUILD_ID="$(aws codebuild start-build --project-name "$BUILD_PROJECT" --region "$AWS_REGION" --query 'build.id' --output text)"
echo "CodeBuild started: $BUILD_ID"
while :; do
  STATUS="$(aws codebuild batch-get-builds --ids "$BUILD_ID" --region "$AWS_REGION" --query 'builds[0].buildStatus' --output text)"
  case "$STATUS" in
    SUCCEEDED) break ;;
    FAILED|FAULT|STOPPED|TIMED_OUT) echo "CodeBuild ended with $STATUS" >&2; exit 1 ;;
    *) sleep 15 ;;
  esac
done

terraform -chdir="$TF_DIR" apply -var=create_api_service=true "$@"
SERVICE_ARN="$(terraform -chdir="$TF_DIR" show -json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(x["values"]["arn"] for x in d["values"]["root_module"]["resources"] if x["address"]=="aws_apprunner_service.api[0]"))')"
aws apprunner start-deployment --service-arn "$SERVICE_ARN" --region "$AWS_REGION" >/dev/null
echo "AWS deployment complete. API: https://$(terraform -chdir="$TF_DIR" output -raw api_url)"
