data "aws_caller_identity" "current" {}
data "aws_vpc" "default" { default = true }
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  subnets      = length(var.subnet_ids) > 0 ? var.subnet_ids : data.aws_subnets.default.ids
  secrets_arns = [for secret in aws_secretsmanager_secret.predsea : secret.arn]
  output_arn   = aws_s3_bucket.outputs.arn
}

resource "aws_s3_bucket" "outputs" { bucket = var.output_bucket_name }
resource "aws_s3_bucket_public_access_block" "outputs" {
  bucket                  = aws_s3_bucket.outputs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "outputs" {
  bucket = aws_s3_bucket.outputs.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "outputs" {
  bucket = aws_s3_bucket.outputs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "outputs" {
  bucket = aws_s3_bucket.outputs.id
  rule {
    id     = "cost-control"
    status = "Enabled"
    filter { prefix = "" }
    noncurrent_version_expiration { noncurrent_days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
  rule {
    id     = "expire-transient-forcing"
    status = "Enabled"
    filter { prefix = "forcing/" }
    expiration { days = 30 }
  }
  rule {
    id     = "expire-transient-logs"
    status = "Enabled"
    filter { prefix = "transient/logs/" }
    expiration { days = 30 }
  }
  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter { prefix = "athena-results/" }
    expiration { days = 30 }
  }
}

resource "aws_ecr_repository" "repos" {
  for_each             = toset(["api", "orchestrator", "wrf", "croco", "ww3", "ecmwf"])
  name                 = "${var.name_prefix}-${each.key}"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}
resource "aws_ecr_lifecycle_policy" "repos" {
  for_each   = aws_ecr_repository.repos
  repository = each.value.name
  policy     = jsonencode({ rules = [{ rulePriority = 1, description = "Retain 20 images", selection = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }, action = { type = "expire" } }] })
}

resource "aws_secretsmanager_secret" "predsea" {
  for_each                = var.secret_names
  name                    = "${var.name_prefix}/${each.value}"
  recovery_window_in_days = 7
}

resource "aws_athena_workgroup" "predsea" {
  name = var.name_prefix
  configuration {
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff_per_query
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    result_configuration {
      output_location = "s3://${aws_s3_bucket.outputs.id}/athena-results/"
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
}
resource "aws_glue_catalog_database" "validation" { name = "predsea_validation" }
resource "aws_glue_catalog_table" "evidence_rows" {
  name          = "evidence_rows"
  database_name = aws_glue_catalog_database.validation.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE", "classification" = "parquet" }
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.outputs.id}/warehouse/evidence_rows/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info { serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe" }
    columns {
      name = "record_type"
      type = "string"
    }
    columns {
      name = "run_id"
      type = "string"
    }
    columns {
      name = "run_date"
      type = "string"
    }
    columns {
      name = "reference_station_id"
      type = "string"
    }
    columns {
      name = "station_id"
      type = "string"
    }
    columns {
      name = "variable"
      type = "string"
    }
    columns {
      name = "value"
      type = "double"
    }
    columns {
      name = "units"
      type = "string"
    }
    columns {
      name = "provider"
      type = "string"
    }
    columns {
      name = "target_time_utc"
      type = "timestamp"
    }
    columns {
      name = "observed_at_utc"
      type = "timestamp"
    }
    columns {
      name = "ingested_at_utc"
      type = "timestamp"
    }
    columns {
      name = "lead_time_hours"
      type = "double"
    }
    columns {
      name = "latitude"
      type = "double"
    }
    columns {
      name = "longitude"
      type = "double"
    }
    columns {
      name = "station_name"
      type = "string"
    }
    columns {
      name = "station_kind"
      type = "string"
    }
    columns {
      name = "network"
      type = "string"
    }
  }
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "ecs_execution" {
  name               = "${var.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role_policy" "ecs_execution_secrets" {
  role   = aws_iam_role.ecs_execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = local.secrets_arns }] })
}
resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
resource "aws_iam_role" "simulation" {
  name               = "${var.name_prefix}-simulation"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}
resource "aws_iam_instance_profile" "simulation" {
  name = "${var.name_prefix}-simulation"
  role = aws_iam_role.simulation.name
}

data "aws_iam_policy_document" "runtime" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [local.output_arn]
  }
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${local.output_arn}/*"]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = local.secrets_arns
  }
  statement {
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution"]
    resources = [aws_athena_workgroup.predsea.arn]
  }
  statement {
    actions   = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
    resources = ["*"]
  }
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
    resources = [aws_ecr_repository.repos["wrf"].arn, aws_ecr_repository.repos["croco"].arn, aws_ecr_repository.repos["ww3"].arn]
  }
}
resource "aws_iam_role_policy" "task_runtime" {
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.runtime.json
}
resource "aws_iam_role_policy" "simulation_runtime" {
  role   = aws_iam_role.simulation.id
  policy = data.aws_iam_policy_document.runtime.json
}
resource "aws_iam_role_policy" "simulation_self_terminate" {
  role   = aws_iam_role.simulation.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["ec2:TerminateInstances"], Resource = "*", Condition = { StringEquals = { "ec2:ResourceTag/CostCenter" = "PredSea", "ec2:ResourceTag/PredSeaDeploymentProfile" = "worker" } } }] })
}
resource "aws_iam_role_policy" "orchestrator_ec2" {
  role = aws_iam_role.task.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ec2:RunInstances", "ec2:CreateTags"], Resource = "*" },
    { Effect = "Allow", Action = ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus", "ec2:DescribeImages", "ec2:DescribeSubnets"], Resource = "*" },
    { Effect = "Allow", Action = ["ec2:TerminateInstances"], Resource = "*", Condition = { StringEquals = { "ec2:ResourceTag/CostCenter" = "PredSea", "ec2:ResourceTag/PredSeaDeploymentProfile" = "worker" } } },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = aws_iam_role.simulation.arn, Condition = { StringEquals = { "iam:PassedToService" = "ec2.amazonaws.com" } } }
  ] })
}

data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "codebuild" {
  name               = "${var.name_prefix}-codebuild"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}
resource "aws_iam_role_policy" "codebuild" {
  role = aws_iam_role.codebuild.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"], Resource = ["${local.output_arn}/codebuild-source/*"] },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"], Resource = [for repo in aws_ecr_repository.repos : repo.arn] }
  ] })
}
resource "aws_codebuild_project" "images" {
  name          = "${var.name_prefix}-images"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 120
  artifacts { type = "NO_ARTIFACTS" }
  environment {
    compute_type    = "BUILD_GENERAL1_LARGE"
    image           = "aws/codebuild/standard:7.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true
    environment_variable {
      name  = "API_REPOSITORY"
      value = aws_ecr_repository.repos["api"].repository_url
    }
    environment_variable {
      name  = "ORCHESTRATOR_REPOSITORY"
      value = aws_ecr_repository.repos["orchestrator"].repository_url
    }
    environment_variable {
      name  = "WRF_REPOSITORY"
      value = aws_ecr_repository.repos["wrf"].repository_url
    }
    environment_variable {
      name  = "CROCO_REPOSITORY"
      value = aws_ecr_repository.repos["croco"].repository_url
    }
    environment_variable {
      name  = "WW3_REPOSITORY"
      value = aws_ecr_repository.repos["ww3"].repository_url
    }
    environment_variable {
      name  = "ECMWF_REPOSITORY"
      value = aws_ecr_repository.repos["ecmwf"].repository_url
    }
  }
  source {
    type      = "S3"
    location  = "${aws_s3_bucket.outputs.id}/codebuild-source/source.zip"
    buildspec = "buildspec.aws.yml"
  }
  logs_config {
    cloudwatch_logs {
      group_name  = "/predsea/codebuild"
      stream_name = "images"
    }
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/predsea/api"
  retention_in_days = 14
}
resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = "/predsea/orchestrator"
  retention_in_days = 30
}
resource "aws_ecs_cluster" "predsea" { name = var.name_prefix }

data "aws_iam_policy_document" "apprunner_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}
data "aws_iam_policy_document" "apprunner_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["tasks.apprunner.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "apprunner_access" {
  name               = "${var.name_prefix}-apprunner-ecr"
  assume_role_policy = data.aws_iam_policy_document.apprunner_assume.json
}
resource "aws_iam_role_policy_attachment" "apprunner_access" {
  role       = aws_iam_role.apprunner_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}
resource "aws_iam_role" "apprunner_instance" {
  name               = "${var.name_prefix}-apprunner-instance"
  assume_role_policy = data.aws_iam_policy_document.apprunner_tasks_assume.json
}
resource "aws_iam_role_policy" "apprunner_runtime" {
  role   = aws_iam_role.apprunner_instance.id
  policy = data.aws_iam_policy_document.runtime.json
}
resource "aws_apprunner_service" "api" {
  count        = var.create_api_service ? 1 : 0
  service_name = "${var.name_prefix}-api"
  source_configuration {
    auto_deployments_enabled = false
    authentication_configuration { access_role_arn = aws_iam_role.apprunner_access.arn }
    image_repository {
      image_identifier      = "${aws_ecr_repository.repos["api"].repository_url}:${var.api_image_tag}"
      image_repository_type = "ECR"
      image_configuration {
        port = "8080"
        runtime_environment_variables = {
          AWS_REGION               = var.aws_region, PREDSEA_STORAGE_BACKEND = "s3", PREDSEA_S3_BUCKET = aws_s3_bucket.outputs.id,
          PREDSEA_S3_PREFIX        = "predictions", PREDSEA_ATHENA_DATABASE = aws_glue_catalog_database.validation.name,
          PREDSEA_ATHENA_WORKGROUP = aws_athena_workgroup.predsea.name, PREDSEA_ATHENA_OUTPUT = "s3://${aws_s3_bucket.outputs.id}/athena-results/", PREDSEA_ENV = "prod"
        }
      }
    }
  }
  instance_configuration {
    cpu               = tostring(var.api_cpu)
    memory            = tostring(var.api_memory)
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }
  health_check_configuration {
    protocol            = "HTTP"
    path                = "/health"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }
}
resource "aws_ecs_task_definition" "orchestrator" {
  family                   = "${var.name_prefix}-orchestrator"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.orchestrator_cpu)
  memory                   = tostring(var.orchestrator_memory)
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{ name = "orchestrator", image = "${aws_ecr_repository.repos["orchestrator"].repository_url}:${var.orchestrator_image_tag}", essential = true, command = ["python", "scripts/aws_daily_orchestrator.py"], environment = [
    { name = "AWS_REGION", value = var.aws_region }, { name = "PREDSEA_S3_BUCKET", value = aws_s3_bucket.outputs.id },
    { name = "PREDSEA_FORECAST_HOURS", value = "72" },
    { name = "PREDSEA_CROCO_GRID_VERSION", value = var.croco_grid_version },
    { name = "PREDSEA_ATHENA_DATABASE", value = aws_glue_catalog_database.validation.name }, { name = "PREDSEA_ATHENA_WORKGROUP", value = aws_athena_workgroup.predsea.name },
    { name = "PREDSEA_EC2_INSTANCE_PROFILE", value = aws_iam_instance_profile.simulation.name },
    { name = "PREDSEA_WRF_IMAGE", value = "${aws_ecr_repository.repos["wrf"].repository_url}:${var.simulation_image_tag}" },
    { name = "PREDSEA_CROCO_IMAGE", value = "${aws_ecr_repository.repos["croco"].repository_url}:${var.simulation_image_tag}" },
    { name = "PREDSEA_WW3_IMAGE", value = "${aws_ecr_repository.repos["ww3"].repository_url}:${var.simulation_image_tag}" },
    { name = "PREDSEA_EC2_SUBNET_IDS", value = join(",", local.subnets) }, { name = "PREDSEA_EC2_SECURITY_GROUP_IDS", value = join(",", var.security_group_ids) }
  ], logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.orchestrator.name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "ecs" } } }])
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}
resource "aws_iam_role_policy" "scheduler" {
  role   = aws_iam_role.scheduler.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["ecs:RunTask"], Resource = aws_ecs_task_definition.orchestrator.arn }, { Effect = "Allow", Action = ["iam:PassRole"], Resource = [aws_iam_role.ecs_execution.arn, aws_iam_role.task.arn] }] })
}
resource "aws_scheduler_schedule" "daily" {
  name                         = "${var.name_prefix}-daily"
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = var.schedule_state
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_ecs_cluster.predsea.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.orchestrator.arn
      launch_type         = "FARGATE"
      task_count          = 1
      network_configuration {
        subnets          = local.subnets
        security_groups  = var.security_group_ids
        assign_public_ip = var.assign_public_ip
      }
    }
  }
}
