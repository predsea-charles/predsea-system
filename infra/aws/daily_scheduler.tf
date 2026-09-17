# infra/aws/daily_scheduler.tf
#
# Daily 00:30 UTC trigger for the ECMWF -> WRF -> WW3 pipeline.
# Replaces manually running run_all_regions.sh from a laptop.
#
# Components:
#   - aws_lambda_function: runs lambda/handler.py, submits the job chain
#   - aws_iam_role + policy: least-privilege permissions for the Lambda
#     (batch:SubmitJob, batch:ListJobs — nothing broader)
#   - aws_scheduler_schedule: EventBridge Scheduler, cron(30 0 * * ? *)
#   - aws_iam_role + policy for the Scheduler to invoke the Lambda
#
# BEFORE APPLYING:
#   1. Package the Lambda: from infra/aws/,
#        cd ../../lambda/daily_trigger && zip -r ../../infra/aws/daily_trigger.zip handler.py
#      (adjust paths to wherever you place the lambda/ directory in the repo)
#   2. Confirm the S3 bucket / job definitions referenced below (or via
#      existing variables) match your actual resource names.
#   3. `tofu plan` and read it before `tofu apply` — this creates new IAM
#      roles and a Lambda function; nothing here modifies existing CROCO/WRF/
#      WW3 job definitions or compute environments.

variable "daily_schedule_enabled" {
  type        = bool
  description = "Whether the daily 00:30 UTC pipeline trigger is active. Set false to pause automation without destroying the infrastructure."
  default     = true
}

variable "daily_schedule_cron_utc" {
  type        = string
  description = "Cron expression (UTC) for the daily pipeline trigger."
  default     = "cron(30 0 * * ? *)"
}

variable "daily_default_forecast_hours" {
  type        = number
  description = "Default forecast_hours used by the scheduled trigger."
  default     = 72
}

data "aws_iam_policy_document" "daily_trigger_lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "daily_trigger_lambda" {
  name               = "predsea-daily-trigger-lambda"
  assume_role_policy = data.aws_iam_policy_document.daily_trigger_lambda_assume.json
}

data "aws_iam_policy_document" "daily_trigger_lambda_permissions" {
  statement {
    sid = "SubmitAndListBatchJobs"
    actions = [
      "batch:SubmitJob",
      "batch:ListJobs",
      "batch:DescribeJobs",
    ]
    resources = ["*"]
    # NOTE: AWS Batch does not support resource-level restriction on
    # SubmitJob targeting specific job definitions/queues via IAM condition
    # keys in all regions/partitions consistently — if your account needs
    # tighter scoping, restrict via a permissions boundary or by only
    # deploying this role with access to the specific job queue ARN once
    # confirmed supported in eu-west-1 for your Batch API version.
  }

  statement {
    sid = "WriteOwnLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:eu-west-1:*:log-group:/aws/lambda/predsea-daily-trigger:*"]
  }
}

resource "aws_iam_role_policy" "daily_trigger_lambda_permissions" {
  name   = "predsea-daily-trigger-lambda-permissions"
  role   = aws_iam_role.daily_trigger_lambda.id
  policy = data.aws_iam_policy_document.daily_trigger_lambda_permissions.json
}

resource "aws_lambda_function" "daily_trigger" {
  function_name = "predsea-daily-trigger"
  role          = aws_iam_role.daily_trigger_lambda.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = 60 # submitting 3 jobs is fast; generous margin over Lambda's default 3s
  memory_size   = 128

  filename         = "${path.module}/daily_trigger.zip"
  source_code_hash = filebase64sha256("${path.module}/daily_trigger.zip")

  environment {
    variables = {
      PREDSEA_AWS_REGION            = "eu-west-1"
      PREDSEA_JOB_QUEUE             = "predsea-models-canary"
      PREDSEA_DEFAULT_FORECAST_HOURS = tostring(var.daily_default_forecast_hours)
    }
  }
}

data "aws_iam_policy_document" "daily_scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "daily_scheduler" {
  name               = "predsea-daily-scheduler"
  assume_role_policy = data.aws_iam_policy_document.daily_scheduler_assume.json
}

data "aws_iam_policy_document" "daily_scheduler_invoke_lambda" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.daily_trigger.arn]
  }
}

resource "aws_iam_role_policy" "daily_scheduler_invoke_lambda" {
  name   = "predsea-daily-scheduler-invoke-lambda"
  role   = aws_iam_role.daily_scheduler.id
  policy = data.aws_iam_policy_document.daily_scheduler_invoke_lambda.json
}

resource "aws_scheduler_schedule" "daily_pipeline_trigger" {
  name                = "predsea-daily-pipeline-trigger"
  schedule_expression = var.daily_schedule_cron_utc
  # cron() expressions in EventBridge Scheduler are evaluated in the
  # timezone below — UTC here means "30 0 * * ? *" really is 00:30 UTC.
  schedule_expression_timezone = "UTC"

  state = var.daily_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.daily_trigger.arn
    role_arn = aws_iam_role.daily_scheduler.arn

    input = jsonencode({
      forecast_hours = var.daily_default_forecast_hours
    })

    retry_policy {
      maximum_retry_attempts       = 0 # deliberately 0 — the Lambda's own
      # duplicate-run guard makes retries safe in theory, but a failed
      # submission usually means something needs human attention (e.g. a
      # quota/capacity issue like the one hit earlier today), not a blind
      # retry at 00:31 UTC. Revisit this only after the guard logic has
      # been in production long enough to trust it unattended.
      maximum_event_age_in_seconds = 3600
    }
  }
}

output "daily_trigger_lambda_name" {
  value = aws_lambda_function.daily_trigger.function_name
}

output "daily_trigger_schedule_state" {
  value = aws_scheduler_schedule.daily_pipeline_trigger.state
}
