#!/usr/bin/env python3
"""Launch and supervise one ephemeral PredSea EC2 Spot simulation worker."""
from __future__ import annotations

import argparse
import base64
import os
import shlex
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

TERMINAL_STATES = {"shutting-down", "terminated", "stopping", "stopped"}
CROCO_REGION_RANKS = {"western_mediterranean_1km": 192}


def validate_region_rank_pairings(pairings: dict[str, int]) -> None:
    """Reject any CROCO submission plan that differs from compiled binaries."""
    if pairings != CROCO_REGION_RANKS:
        details = []
        for region in sorted(set(pairings) | set(CROCO_REGION_RANKS)):
            actual = pairings.get(region)
            expected = CROCO_REGION_RANKS.get(region)
            if actual != expected:
                details.append(f"{region}: got {actual!r}, expected {expected!r}")
        raise ValueError("CROCO region/rank preflight failed: " + "; ".join(details))


def _q(value: str) -> str:
    return shlex.quote(str(value))


def build_user_data(
    *, region: str, bucket: str, run_date: str, run_id: str,
    wrf_image_uri: str, croco_image_uri: str, ww3_image_uri: str,
    forecast_hours: int, mpi_ranks: int, croco_grid_version: str,
    worker_max_age_hours: float = 26,
    croco_inputs_prefix: str = "",
    croco_region_ranks: dict[str, int] | None = None,
) -> str:
    """Create the boot script for the sequential WRF, CROCO, and WW3 chain."""
    rank_plan = dict(croco_region_ranks or CROCO_REGION_RANKS)
    validate_region_rank_pairings(rank_plan)
    registries = sorted({uri.split("/", 1)[0] for uri in (wrf_image_uri, croco_image_uri, ww3_image_uri)})
    output_uri = f"s3://{bucket}/predictions/{run_date}/runs/{run_id}"
    forcing_uri = f"s3://{bucket}/forcing"
    return f"""#!/bin/bash
set -Eeuo pipefail
exec > >(tee -a /var/log/predsea-simulation.log) 2>&1
AWS_REGION={_q(region)}
BUCKET={_q(bucket)}
RUN_DATE={_q(run_date)}
RUN_ID={_q(run_id)}
WRF_IMAGE_URI={_q(wrf_image_uri)}
CROCO_IMAGE_URI={_q(croco_image_uri)}
WW3_IMAGE_URI={_q(ww3_image_uri)}
MPI_RANKS={int(mpi_ranks)}
CROCO_GRID_VERSION={_q(croco_grid_version)}
CROCO_INPUTS_PREFIX={_q(croco_inputs_prefix)}
OUTPUT_URI={_q(output_uri)}
STATUS=FAILED
WORKER_MAX_AGE_HOURS={float(worker_max_age_hours)}
INSTANCE_ID="$(curl -fsS http://169.254.169.254/latest/api/token -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600' | xargs -I{{}} curl -fsS -H 'X-aws-ec2-metadata-token: {{}}' http://169.254.169.254/latest/meta-data/instance-id)"
systemd-run --unit=predsea-worker-ttl --on-active="${{WORKER_MAX_AGE_HOURS}}h" /sbin/shutdown -h now
finish() {{
  rc=$?
  mkdir -p /workspace/outputs
  printf '{{"status":"%s","exit_code":%s,"instance_id":"%s"}}\n' "$STATUS" "$rc" "$INSTANCE_ID" >/workspace/outputs/SIMULATION_STATUS.json
  aws s3 sync /workspace/outputs/ "$OUTPUT_URI/" --only-show-errors || true
  aws s3 cp /var/log/predsea-simulation.log "s3://$BUCKET/transient/logs/$RUN_DATE/$RUN_ID/ec2-user-data.log" --only-show-errors || true
  aws ec2 terminate-instances --region "$AWS_REGION" --instance-ids "$INSTANCE_ID" || shutdown -h now
}}
trap finish EXIT

if command -v dnf >/dev/null; then dnf install -y docker awscli; else apt-get update && apt-get install -y docker.io awscli; fi
systemctl enable --now docker
mkdir -p /workspace/inputs/ecmwf /workspace/outputs/wrf /workspace/outputs/croco /workspace/outputs/ww3
chmod 0775 /workspace/inputs
{os.linesep.join(f'aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin {_q(registry)}' for registry in registries)}
aws s3 sync {_q(forcing_uri)}/ecmwf/$RUN_DATE/ /workspace/inputs/ecmwf/ --only-show-errors
docker pull "$WRF_IMAGE_URI"
docker pull "$CROCO_IMAGE_URI"
docker pull "$WW3_IMAGE_URI"

START_DATE="${{RUN_DATE}}_00:00:00"
END_DATE="$(date -u -d "$RUN_DATE + {int(forecast_hours)} hours" '+%Y-%m-%d_%H:%M:%S')"

echo "[1/3] Running WRF with $MPI_RANKS MPI ranks"
docker run --rm --name predsea-wrf --shm-size=32g \
  -e AWS_REGION="$AWS_REGION" -e PREDSEA_S3_BUCKET="$BUCKET" \
  -e PREDSEA_RUN_DATE="$RUN_DATE" -e PREDSEA_RUN_ID="$RUN_ID" \
  -e PREDSEA_FORECAST_HOURS={int(forecast_hours)} -e START_DATE="$START_DATE" -e END_DATE="$END_DATE" \
  -e MPI_PROCS="$MPI_RANKS" -e MPI_NPROC_X=16 -e MPI_NPROC_Y=8 \
  -e MPI_EXTRA_ARGS="--use-hwthread-cpus --bind-to hwthread --map-by hwthread" \
  -e GRIB_DIR=/data -e RUN_DIR=/workspace/outputs/wrf \
  -v /workspace/inputs/ecmwf:/data:ro -v /workspace/outputs:/workspace/outputs \
  "$WRF_IMAGE_URI" /opt/predsea/run_pipeline.sh
aws s3 sync /workspace/outputs/wrf/ "$OUTPUT_URI/wrf/" --only-show-errors

echo "Preparing WW3 wind forcing from this run's WRF d02 outputs"
mkdir -p /workspace/inputs/ww3
docker run --rm --entrypoint python3 \
  -v /workspace/outputs/wrf:/workspace/wrf:ro -v /workspace/inputs/ww3:/workspace/ww3 \
  "$WW3_IMAGE_URI" /app/scripts/prepare_ww3_wind_from_wrf.py \
  --wrf-dir /workspace/wrf --output-base-dir /workspace/ww3
aws s3 sync /workspace/inputs/ww3/ "s3://$BUCKET/forcing/ww3/$RUN_DATE/" --only-show-errors

echo "[2/3] Running unified Western Mediterranean CROCO simulation"
for REGION_RANK_PAIR in {' '.join(f'{region}:{ranks}' for region, ranks in rank_plan.items())}; do
  REGION_ID="${{REGION_RANK_PAIR%%:*}}"
  CROCO_MPI_RANKS="${{REGION_RANK_PAIR##*:}}"
  docker run --rm --name "predsea-croco-${{REGION_ID//_/-}}" --shm-size=16g \
    -e AWS_REGION="$AWS_REGION" -e PREDSEA_STORAGE_BACKEND=s3 \
    -e PREDSEA_RUN_DATE="$RUN_DATE" -e PREDSEA_RUN_ID="$RUN_ID" \
    -e PREDSEA_CROCO_GRID_S3_URI="s3://$BUCKET/static/native-marine/$REGION_ID/croco-grid/$CROCO_GRID_VERSION/croco_grid.nc" \
    -e PREDSEA_WRF_S3_URI="$OUTPUT_URI/wrf/" \
    -e PREDSEA_CROCO_OCEAN_SOURCE=cmems \
    -v /workspace/inputs:/workspace/inputs:rw -v /workspace/outputs:/workspace/outputs \
    "$CROCO_IMAGE_URI" --model=croco --region="$REGION_ID" \
    --forecast-hours={int(forecast_hours)} --mpi-ranks="$CROCO_MPI_RANKS" --s3-bucket="$BUCKET"
done

echo "[3/3] Running regional WW3 simulations"
for REGION_ID in alboran_1km algerian_1km balearic_1km gulf_of_lion_1km tyrrhenian_1km; do
  docker run --rm --name "predsea-ww3-${{REGION_ID//_/-}}" --shm-size=16g \
    -e AWS_REGION="$AWS_REGION" -e PREDSEA_STORAGE_BACKEND=s3 \
    -v /workspace/inputs:/workspace/inputs:ro -v /workspace/outputs:/workspace/outputs \
    "$WW3_IMAGE_URI" --model=ww3 --region="$REGION_ID" \
    --forecast-hours={int(forecast_hours)} --mpi-ranks=24 --s3-bucket="$BUCKET" \
    --run-date="$RUN_DATE" --run-id="$RUN_ID"
done
STATUS=SUCCESS
"""


class SpotOrchestrator:
    def __init__(self, region: str, *, ec2=None, s3=None):
        self.region = region
        self.ec2 = ec2 or boto3.client("ec2", region_name=region)
        self.s3 = s3 or boto3.client("s3", region_name=region)

    def launch(self, args) -> str:
        run_date = args.run_date or datetime.now(timezone.utc).date().isoformat()
        run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        rank_plan = dict(getattr(args, "croco_region_ranks", CROCO_REGION_RANKS))
        validate_region_rank_pairings(rank_plan)
        user_data = build_user_data(
            region=self.region, bucket=args.bucket, run_date=run_date, run_id=run_id,
            wrf_image_uri=args.wrf_image_uri, croco_image_uri=args.croco_image_uri,
            ww3_image_uri=args.ww3_image_uri, forecast_hours=args.forecast_hours,
            mpi_ranks=args.mpi_ranks, croco_grid_version=args.croco_grid_version,
            worker_max_age_hours=args.worker_max_age_hours,
            croco_inputs_prefix=getattr(args, "croco_inputs_prefix", ""),
            croco_region_ranks=rank_plan,
        )
        request = {
            "ImageId": args.ami_id,
            "InstanceType": args.instance_type,
            "MinCount": 1, "MaxCount": 1,
            "IamInstanceProfile": {"Name": args.instance_profile},
            "UserData": base64.b64encode(user_data.encode()).decode(),
            "InstanceMarketOptions": {"MarketType": "spot", "SpotOptions": {"SpotInstanceType": "one-time", "InstanceInterruptionBehavior": "terminate"}},
            "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": args.volume_gb, "VolumeType": "gp3", "Iops": args.volume_iops, "Throughput": args.volume_throughput, "DeleteOnTermination": True, "Encrypted": True}}],
            "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"},
            "InstanceInitiatedShutdownBehavior": "terminate",
            "TagSpecifications": [{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": f"predsea-sim-{run_id.lower()}"}, {"Key": "PredSeaRunId", "Value": run_id}, {"Key": "CostCenter", "Value": "PredSea"}, {"Key": "PredSeaDeploymentProfile", "Value": "worker"}]}],
        }
        if args.subnet_id: request["SubnetId"] = args.subnet_id
        if args.security_group_ids: request["SecurityGroupIds"] = args.security_group_ids
        response = self.ec2.run_instances(**request)
        return response["Instances"][0]["InstanceId"]

    def status_marker(self, bucket: str, run_date: str, run_id: str) -> str | None:
        key = f"predictions/{run_date}/runs/{run_id}/SIMULATION_STATUS.json"
        try:
            body = self.s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()
            import json
            return json.loads(body).get("status")
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}: return None
            raise

    def wait(self, instance_id: str, *, bucket: str, run_date: str, run_id: str, timeout_seconds: int, poll_seconds: int = 20) -> str:
        deadline = time.monotonic() + timeout_seconds
        last_console = ""
        while time.monotonic() < deadline:
            marker = self.status_marker(bucket, run_date, run_id)
            if marker: return marker
            response = self.ec2.describe_instances(InstanceIds=[instance_id])
            state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
            try:
                console = self.ec2.get_console_output(InstanceId=instance_id, Latest=True).get("Output", "")
                if console and console != last_console:
                    print(console[len(last_console):], end="")
                    last_console = console
            except ClientError:
                pass
            if state in TERMINAL_STATES:
                return self.status_marker(bucket, run_date, run_id) or "FAILED"
            time.sleep(poll_seconds)
        self.ec2.terminate_instances(InstanceIds=[instance_id])
        raise TimeoutError(f"Simulation instance {instance_id} exceeded {timeout_seconds}s and was terminated")


def default_ami(ec2) -> str:
    images = ec2.describe_images(Owners=["amazon"], Filters=[{"Name": "name", "Values": ["al2023-ami-2023*-x86_64"]}, {"Name": "state", "Values": ["available"]}])["Images"]
    return max(images, key=lambda image: image["CreationDate"])["ImageId"]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--region", default=os.getenv("AWS_REGION", "eu-west-1")); p.add_argument("--bucket", default=os.getenv("PREDSEA_S3_BUCKET", "predsea-daily-outputs"))
    p.add_argument("--wrf-image-uri", default=os.getenv("PREDSEA_WRF_IMAGE"), required=not bool(os.getenv("PREDSEA_WRF_IMAGE")))
    p.add_argument("--croco-image-uri", default=os.getenv("PREDSEA_CROCO_IMAGE"), required=not bool(os.getenv("PREDSEA_CROCO_IMAGE")))
    p.add_argument("--ww3-image-uri", default=os.getenv("PREDSEA_WW3_IMAGE"), required=not bool(os.getenv("PREDSEA_WW3_IMAGE")))
    p.add_argument("--instance-profile", default=os.getenv("PREDSEA_EC2_INSTANCE_PROFILE"), required=not bool(os.getenv("PREDSEA_EC2_INSTANCE_PROFILE")))
    p.add_argument("--instance-type", default="c6i.32xlarge"); p.add_argument("--ami-id"); p.add_argument("--subnet-id", default=(os.getenv("PREDSEA_EC2_SUBNET_IDS", "").split(",")[0] or None))
    p.add_argument("--security-group-ids", default=os.getenv("PREDSEA_EC2_SECURITY_GROUP_IDS", "")); p.add_argument("--volume-gb", type=int, default=300)
    p.add_argument("--volume-iops", type=int, default=3000); p.add_argument("--volume-throughput", type=int, default=500)
    p.add_argument("--forecast-hours", type=int, default=72); p.add_argument("--mpi-ranks", type=int, default=128)
    p.add_argument("--croco-grid-version", default=os.getenv("PREDSEA_CROCO_GRID_VERSION"), required=not bool(os.getenv("PREDSEA_CROCO_GRID_VERSION")))
    p.add_argument("--croco-inputs-prefix", default=os.getenv("PREDSEA_CROCO_INPUTS_S3_PREFIX", ""), help="S3 prefix containing one directory per region with croco_ini.nc, croco_bry.nc, and croco_clm.nc")
    p.add_argument("--run-date"); p.add_argument("--run-id"); p.add_argument("--timeout-hours", type=float, default=24)
    p.add_argument("--worker-max-age-hours", type=float, default=26)
    return p


def main() -> int:
    cli_parser = parser()
    args = cli_parser.parse_args(); args.security_group_ids = [v for v in args.security_group_ids.split(",") if v]
    if args.forecast_hours != 72:
        cli_parser.error("AWS production runs are fixed at 72 forecast hours")
    if args.mpi_ranks != 128:
        cli_parser.error("c6i.32xlarge WRF runs require 128 MPI ranks")
    if args.croco_inputs_prefix and not args.croco_inputs_prefix.startswith("s3://"):
        cli_parser.error("--croco-inputs-prefix must be an s3:// prefix")
    if args.worker_max_age_hours <= args.timeout_hours:
        cli_parser.error("worker max age must exceed the supervisor timeout")
    now = datetime.now(timezone.utc); args.run_date = args.run_date or now.date().isoformat(); args.run_id = args.run_id or now.strftime("%Y-%m-%dT%H%MZ")
    orchestrator = SpotOrchestrator(args.region)
    args.ami_id = args.ami_id or default_ami(orchestrator.ec2)
    instance_id = orchestrator.launch(args); print(f"Launched {instance_id} for {args.run_id}")
    status = orchestrator.wait(instance_id, bucket=args.bucket, run_date=args.run_date, run_id=args.run_id, timeout_seconds=int(args.timeout_hours * 3600))
    print(f"Simulation status: {status}"); return 0 if status == "SUCCESS" else 1


if __name__ == "__main__": raise SystemExit(main())
