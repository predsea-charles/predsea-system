import base64
from types import SimpleNamespace

import pytest

from scripts.aws_orchestrator import (
    CROCO_REGION_RANKS,
    SpotOrchestrator,
    build_user_data,
    validate_region_rank_pairings,
)


class FakeEC2:
    def __init__(self): self.request = None
    def run_instances(self, **kwargs): self.request = kwargs; return {"Instances": [{"InstanceId": "i-123"}]}


def test_user_data_has_durable_upload_and_termination_trap():
    script = build_user_data(
        region="eu-west-1", bucket="bucket", run_date="2026-08-23", run_id="run",
        wrf_image_uri="123.dkr.ecr.eu-west-1.amazonaws.com/wrf:tag",
        croco_image_uri="123.dkr.ecr.eu-west-1.amazonaws.com/croco:tag",
        ww3_image_uri="123.dkr.ecr.eu-west-1.amazonaws.com/ww3:tag",
        forecast_hours=72, mpi_ranks=128, croco_grid_version="20260823-v1",
    )
    assert "trap finish EXIT" in script
    assert "SIMULATION_STATUS.json" in script
    assert "aws ec2 terminate-instances" in script
    assert "systemd-run --unit=predsea-worker-ttl --on-active=\"${WORKER_MAX_AGE_HOURS}h\"" in script
    assert "transient/logs/$RUN_DATE/$RUN_ID/ec2-user-data.log" in script
    assert "aws s3 sync /workspace/outputs/" in script
    assert "MPI_RANKS=128" in script
    assert "--use-hwthread-cpus" in script
    assert "Running unified Western Mediterranean CROCO" in script
    assert "Running regional WW3" in script
    assert "cmems/$RUN_DATE/ /workspace/inputs/" not in script
    assert "PREDSEA_CROCO_OCEAN_SOURCE=cmems" in script
    for region, ranks in CROCO_REGION_RANKS.items():
        assert f"{region}:{ranks}" in script
    assert '--mpi-ranks="$CROCO_MPI_RANKS"' in script
    assert "-v /workspace/inputs:/workspace/inputs:rw" in script


def test_launch_requests_one_time_terminating_spot_instance():
    ec2 = FakeEC2(); service = SpotOrchestrator("eu-west-1", ec2=ec2, s3=object())
    args = SimpleNamespace(
        run_date="2026-08-23", run_id="run", bucket="bucket",
        wrf_image_uri="123.dkr.ecr.eu-west-1.amazonaws.com/wrf:tag",
        croco_image_uri="123.dkr.ecr.eu-west-1.amazonaws.com/croco:tag",
        ww3_image_uri="123.dkr.ecr.eu-west-1.amazonaws.com/ww3:tag",
        forecast_hours=72, mpi_ranks=128, croco_grid_version="20260823-v1", ami_id="ami-1",
        instance_type="c6i.32xlarge", instance_profile="predsea-simulation",
        volume_gb=300, volume_iops=3000, volume_throughput=500,
        subnet_id="subnet-1", security_group_ids=[],
        worker_max_age_hours=26,
    )
    assert service.launch(args) == "i-123"
    options = ec2.request["InstanceMarketOptions"]["SpotOptions"]
    assert options["SpotInstanceType"] == "one-time"
    assert options["InstanceInterruptionBehavior"] == "terminate"
    assert ec2.request["MetadataOptions"]["HttpTokens"] == "required"
    assert ec2.request["InstanceInitiatedShutdownBehavior"] == "terminate"
    assert {"Key": "PredSeaDeploymentProfile", "Value": "worker"} in ec2.request["TagSpecifications"][0]["Tags"]
    ebs = ec2.request["BlockDeviceMappings"][0]["Ebs"]
    assert ebs["VolumeSize"] == 300
    assert ebs["Iops"] == 3000
    assert ebs["Throughput"] == 500
    assert "trap finish EXIT" in base64.b64decode(ec2.request["UserData"]).decode()


def test_region_rank_preflight_rejects_mismatch_before_ec2_submission():
    ec2 = FakeEC2(); service = SpotOrchestrator("eu-west-1", ec2=ec2, s3=object())
    args = SimpleNamespace(
        run_date="2026-08-23", run_id="run", bucket="bucket",
        wrf_image_uri="example/wrf:tag", croco_image_uri="example/croco:tag",
        ww3_image_uri="example/ww3:tag", forecast_hours=72, mpi_ranks=128,
        croco_grid_version="v1", ami_id="ami-1", instance_type="c6i.32xlarge",
        instance_profile="profile", volume_gb=300, volume_iops=3000,
        volume_throughput=500, subnet_id=None, security_group_ids=[],
        worker_max_age_hours=26,
        croco_region_ranks={"western_mediterranean_1km": 96},
    )
    with pytest.raises(
        ValueError,
        match="western_mediterranean_1km: got 96, expected 192",
    ):
        service.launch(args)
    assert ec2.request is None


def test_region_rank_preflight_accepts_canonical_contract():
    validate_region_rank_pairings(dict(CROCO_REGION_RANKS))
