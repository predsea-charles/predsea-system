locals {
  croco_regions = {
    alboran_1km      = { mpi_ranks = 16 }
    algerian_1km     = { mpi_ranks = 24 }
    balearic_1km     = { mpi_ranks = 32 }
    gulf_of_lion_1km = { mpi_ranks = 8 }
    tyrrhenian_1km   = { mpi_ranks = 48 }
  }

  fixed_hpc_jobs = {
    ecmwf = {
      vcpus        = 4
      memory       = 8000
      image_digest = var.ecmwf_image_digest
      command = [
        "--run-date", "Ref::run_date",
        "--lead-hours", "Ref::lead_hours",
        "--s3-bucket", aws_s3_bucket.outputs.id,
      ]
      environment = []
      parameters = {
        run_date   = "override-at-submission"
        lead_hours = "24"
      }
    }
    wrf = {
      vcpus        = 128
      memory       = 240000
      image_digest = var.wrf_image_digest
      command = [
        "--run-date", "Ref::run_date",
        "--run-id", "Ref::run_id",
        "--forecast-hours", "Ref::forecast_hours",
        "--s3-bucket", aws_s3_bucket.outputs.id,
      ]
      environment = [
        { name = "MPI_PROCS", value = "128" },
        { name = "MPI_NPROC_X", value = "16" },
        { name = "MPI_NPROC_Y", value = "8" },
        { name = "MPI_EXTRA_ARGS", value = "--use-hwthread-cpus --bind-to hwthread --map-by hwthread" },
        { name = "PREDSEA_WRF_GEOG_RES", value = "lowres+modis_30s_lake+default" },
      ]
      parameters = {
        run_date       = "override-at-submission"
        run_id         = "override-at-submission"
        forecast_hours = "6"
      }
    }
    ww3 = {
      # Reserve the full node while retaining the validated 24-rank runtime.
      vcpus        = 24
      memory       = 48000
      image_digest = var.ww3_image_digest
      command = [
        "--model", "ww3",
        "--region", "Ref::region",
        "--forecast-hours", "Ref::forecast_hours",
        "--mpi-ranks", "24",
        "--s3-bucket", aws_s3_bucket.outputs.id,
        "--run-date", "Ref::run_date",
        "--run-id", "Ref::run_id",
      ]
      environment = []
      parameters = {
        forecast_hours = "6"
        run_date       = "override-at-submission"
        run_id         = "override-at-submission"
      }
    }
  }

  croco_hpc_jobs = {
    for region, spec in local.croco_regions : "croco_${region}" => {
      vcpus  = spec.mpi_ranks
      memory = 30000
      command = [
        "--region", "Ref::region",
        "--model", "croco",
        "--forecast-hours", "Ref::forecast_hours",
        "--mpi-ranks", "Ref::mpi_ranks",
        "--run-date", "Ref::run_date",
        "--run-id", "Ref::run_id",
        "--s3-bucket", aws_s3_bucket.outputs.id,
      ]
      environment = [
        { name = "PREDSEA_CROCO_OCEAN_SOURCE", value = "cmems" },
        { name = "PREDSEA_CROCO_GRID_S3_URI", value = "s3://${aws_s3_bucket.outputs.id}/static/native-marine/${region}/croco-grid/v1.0/croco_grid.nc" },
        { name = "PREDSEA_WRF_S3_URI", value = "s3://${aws_s3_bucket.outputs.id}/predictions/Ref::run_date/runs/Ref::run_id/wrf/" },
        { name = "PREDSEA_RUN_DATE", value = "Ref::run_date" },
        { name = "PREDSEA_RUN_ID", value = "Ref::run_id" },
      ]
      secrets = [
        { name = "COPERNICUS_USERNAME", valueFrom = "arn:aws:secretsmanager:eu-west-1:671460501982:secret:predsea/COPERNICUS_USERNAME-ZJe5L0" },
        { name = "COPERNICUS_PASSWORD", valueFrom = "arn:aws:secretsmanager:eu-west-1:671460501982:secret:predsea/COPERNICUS_PASSWORD-7QNNi2" },
      ]
      parameters = {
        mpi_ranks      = tostring(spec.mpi_ranks)
        forecast_hours = "72"
        run_date       = "override-at-submission"
        run_id         = "override-at-submission"
      }
      image_key    = "croco"
      log_key      = "croco"
      image_digest = var.croco_image_digest
    }
  }

  hpc_jobs = merge(
    {
      for name, spec in local.fixed_hpc_jobs : name => merge(spec, {
        image_key = name
        log_key   = name
      })
    },
    local.croco_hpc_jobs,
  )
}

resource "aws_iam_role" "batch_instance" {
  name               = "${var.name_prefix}-batch-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "batch_instance_ecs" {
  role       = aws_iam_role.batch_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_instance_profile" "batch" {
  name = "${var.name_prefix}-batch-instance"
  role = aws_iam_role.batch_instance.name
}

data "aws_iam_policy_document" "spot_fleet_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["spotfleet.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "batch_spot_fleet" {
  name               = "${var.name_prefix}-batch-spot-fleet"
  assume_role_policy = data.aws_iam_policy_document.spot_fleet_assume.json
}

resource "aws_iam_role_policy_attachment" "batch_spot_fleet" {
  role       = aws_iam_role.batch_spot_fleet.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2SpotFleetTaggingRole"
}

resource "aws_security_group" "hpc" {
  name        = "${var.name_prefix}-batch"
  description = "PredSea AWS Batch compute nodes"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "MPI traffic between Batch compute nodes"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  egress {
    description = "Model inputs, images, logs, and outputs"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_launch_template" "hpc" {
  name_prefix = "${var.name_prefix}-batch-"

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      encrypted   = true
      volume_size = var.batch_root_volume_size_gib
      volume_type = "gp3"
      iops        = 3000
      throughput  = 500
    }
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
}

resource "aws_batch_compute_environment" "spot" {
  compute_environment_name = "${var.name_prefix}-models-spot"
  state                    = "ENABLED"
  type                     = "MANAGED"

  compute_resources {
    type                = "SPOT"
    allocation_strategy = "SPOT_PRICE_CAPACITY_OPTIMIZED"
    min_vcpus           = 0
    desired_vcpus       = 0
    max_vcpus           = 128
    instance_type       = var.batch_instance_types
    instance_role       = aws_iam_instance_profile.batch.arn
    spot_iam_fleet_role = aws_iam_role.batch_spot_fleet.arn
    subnets             = local.subnets
    security_group_ids  = concat([aws_security_group.hpc.id], var.security_group_ids)

    launch_template {
      launch_template_id = aws_launch_template.hpc.id
      version            = "$Latest"
    }

    tags = merge(var.tags, {
      Name                     = "${var.name_prefix}-batch-model"
      PredSeaDeploymentProfile = "batch"
    })
  }

  depends_on = [
    aws_iam_role_policy_attachment.batch_instance_ecs,
    aws_iam_role_policy_attachment.batch_spot_fleet,
  ]
}

# AWS Batch job queues try compute environments in order. The scale-to-zero
# On-Demand pool is used only when the preferred Spot pool cannot place a job.
resource "aws_batch_compute_environment" "on_demand" {
  compute_environment_name = "${var.name_prefix}-models-on-demand"
  state                    = "ENABLED"
  type                     = "MANAGED"

  compute_resources {
    type                = "EC2"
    allocation_strategy = "BEST_FIT_PROGRESSIVE"
    min_vcpus           = 0
    desired_vcpus       = 0
    max_vcpus           = 128
    instance_type       = var.batch_instance_types
    instance_role       = aws_iam_instance_profile.batch.arn
    subnets             = local.subnets
    security_group_ids  = concat([aws_security_group.hpc.id], var.security_group_ids)

    launch_template {
      launch_template_id = aws_launch_template.hpc.id
      version            = "$Latest"
    }

    tags = merge(var.tags, {
      Name                     = "${var.name_prefix}-batch-model-on-demand"
      PredSeaDeploymentProfile = "batch"
    })
  }

  depends_on = [aws_iam_role_policy_attachment.batch_instance_ecs]
}

resource "aws_batch_job_queue" "models" {
  name     = "${var.name_prefix}-models"
  state    = "ENABLED"
  priority = 10

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.spot.arn
  }

  compute_environment_order {
    order               = 2
    compute_environment = aws_batch_compute_environment.on_demand.arn
  }
}

# Paid canaries must never fall back to On-Demand capacity. Scale-to-zero Spot
# plus bounded job timeouts keeps the experiment inside its authorized ceiling.
resource "aws_batch_job_queue" "canary" {
  name     = "${var.name_prefix}-models-canary"
  state    = "ENABLED"
  priority = 20
  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.spot.arn
  }
}

resource "aws_batch_job_definition" "model" {
  for_each = local.hpc_jobs

  name                  = "${var.name_prefix}-${each.key}-hpc"
  type                  = "container"
  platform_capabilities = ["EC2"]
  propagate_tags        = true
  parameters            = each.value.parameters

  container_properties = jsonencode({
    image            = try(each.value.image_digest, "") != "" ? "${aws_ecr_repository.repos[each.value.image_key].repository_url}@${each.value.image_digest}" : "${aws_ecr_repository.repos[each.value.image_key].repository_url}:${var.simulation_image_tag}"
    command          = each.value.command
    executionRoleArn = aws_iam_role.ecs_execution.arn
    jobRoleArn       = aws_iam_role.task.arn
    environment = concat(each.value.environment, [
      { name = "AWS_REGION", value = var.aws_region },
      { name = "PREDSEA_S3_BUCKET", value = aws_s3_bucket.outputs.id },
    ])
    secrets = try(each.value.secrets, [])
    resourceRequirements = [
      { type = "VCPU", value = tostring(each.value.vcpus) },
      { type = "MEMORY", value = tostring(each.value.memory) },
    ]
    linuxParameters = {
      sharedMemorySize = 8192
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.model[each.value.log_key].name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "batch"
      }
    }
  })

  retry_strategy {
    attempts = 1
  }

  timeout {
    attempt_duration_seconds = each.key == "wrf" ? 5400 : 3600
  }
}
