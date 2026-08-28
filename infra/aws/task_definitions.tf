locals {
  model_tasks = {
    wrf   = {}
    croco = {}
    ww3   = {}
  }
}

resource "aws_cloudwatch_log_group" "model" {
  for_each = local.model_tasks

  name              = "/predsea/${each.key}"
  retention_in_days = 30
}
