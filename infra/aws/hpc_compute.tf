locals {
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
      vcpus        = 192
      memory       = 240000
      image_digest = var.wrf_image_digest
      command = [
        "--run-date", "Ref::run_date",
        "--run-id", "Ref::run_id",
        "--forecast-hours", "Ref::forecast_hours",
        "--s3-bucket", aws_s3_bucket.outputs.id,
      ]
      environment = [
        { name = "MPI_PROCS", value = "192" },
        { name = "MPI_NPROC_X", value = "16" },
        { name = "MPI_NPROC_Y", value = "12" },
        { name = "MPI_EXTRA_ARGS", value = "" },
        { name = "PREDSEA_WRF_GEOG_RES", value = "modis_landuse_20class_30s_with_lakes+default" },
      ]
      parameters = {
        run_date       = "override-at-submission"
        run_id         = "override-at-submission"
        forecast_hours = "72"
      }
    }
    ww3 = {
      vcpus        = 192
      memory       = 380000
      image_digest = var.ww3_image_digest
      command = [
        "--model", "ww3",
        "--region", "Ref::region",
        "--forecast-hours", "Ref::forecast_hours",
        "--mpi-ranks", "Ref::mpi_ranks",
        "--s3-bucket", aws_s3_bucket.outputs.id,
        "--run-date", "Ref::run_date",
        "--run-id", "Ref::run_id",
      ]
      environment = []
      parameters = {
        region         = "western_mediterranean_2km"
        forecast_hours = "72"
        mpi_ranks      = "192" # Synchronized with vcpus = 192
        run_date       = "override-at-submission"
        run_id         = "override-at-submission"
      }
    }
  }

  hpc_jobs = {
    for name, spec in local.fixed_hpc_jobs : name => merge(spec, {
      image_key = name
      log_key   = name
    })
  }
}

resource "aws_iam_role" "batch_instance" {
  name               = "${var.name_prefix}-batch-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# Updated to non-deprecated managed policy
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
    max_vcpus           = 300 # Covers WRF (192 vCPUs) and WW3 (192 vCPUs) concurrently.
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

resource "aws_batch_compute_environment" "on_demand" {
  compute_environment_name = "${var.name_prefix}-models-on-demand"
  state                    = "ENABLED"
  type                     = "MANAGED"

  compute_resources {
    type                = "EC2"
    allocation_strategy = "BEST_FIT_PROGRESSIVE"
    min_vcpus           = 0
    desired_vcpus       = 0
    max_vcpus           = 300
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

  update_policy {
    job_execution_timeout_minutes = 30
    terminate_jobs_on_update      = false
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

resource "aws_batch_job_queue" "canary" {
  name     = "${var.name_prefix}-models-canary"
  state    = "ENABLED"
  priority = 20

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.spot.arn
  }

  compute_environment_order {
    order               = 2
    compute_environment = aws_batch_compute_environment.on_demand.arn
  }
}

resource "aws_batch_job_definition" "model" {
  for_each              = local.hpc_jobs
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
    attempts = each.key == "wrf" ? 3 : (each.key == "ww3" ? 2 : 1)

    # Retry on Spot interruption; exit immediately on real failures.
    dynamic "evaluate_on_exit" {
      for_each = each.key == "wrf" ? [1] : []
      content {
        on_reason = "Host EC2*"
        action    = "RETRY"
      }
    }
    dynamic "evaluate_on_exit" {
      for_each = each.key == "wrf" ? [1] : []
      content {
        on_exit_code = "0"
        action       = "EXIT"
      }
    }
  }

  timeout {
    attempt_duration_seconds = each.key == "ww3" ? 86400 : (each.key == "ecmwf" ? 3600 : (1800 + tonumber(try(each.value.parameters.forecast_hours, "6")) * 600))
  }
}
