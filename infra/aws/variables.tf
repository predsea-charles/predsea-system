variable "aws_region" {
  type    = string
  default = "eu-west-1"
}
variable "name_prefix" {
  type    = string
  default = "predsea"
}
variable "output_bucket_name" {
  type    = string
  default = "predsea-daily-outputs"
}
variable "athena_bytes_scanned_cutoff_per_query" {
  type        = number
  description = "Maximum bytes Athena may scan for one query in the PredSea workgroup"
  default     = 10737418240
  validation {
    condition     = var.athena_bytes_scanned_cutoff_per_query >= 10485760
    error_message = "athena_bytes_scanned_cutoff_per_query must be at least Athena's 10 MiB minimum."
  }
}
variable "schedule_expression" {
  type    = string
  default = "cron(0 3 * * ? *)"
}
variable "schedule_state" {
  type    = string
  default = "DISABLED"
  validation {
    condition     = contains(["ENABLED", "DISABLED"], var.schedule_state)
    error_message = "schedule_state must be ENABLED or DISABLED."
  }
}
variable "orchestrator_cpu" {
  type    = number
  default = 2048
}
variable "orchestrator_memory" {
  type    = number
  default = 8192
}
variable "api_cpu" {
  type    = number
  default = 1024
}
variable "api_memory" {
  type    = number
  default = 2048
}
variable "api_desired_count" {
  type    = number
  default = 1
}
variable "api_image_tag" {
  type    = string
  default = "latest"
}
variable "orchestrator_image_tag" {
  type    = string
  default = "latest"
}
variable "simulation_image_tag" {
  type    = string
  default = "latest"
}
variable "croco_grid_version" {
  type        = string
  description = "Validated immutable CROCO grid version present for every region in S3"
}
variable "subnet_ids" {
  type    = list(string)
  default = []
}
variable "security_group_ids" {
  type    = list(string)
  default = []
}
variable "assign_public_ip" {
  type    = bool
  default = true
}
variable "create_api_service" {
  type    = bool
  default = true
}
variable "secret_names" {
  type    = set(string)
  default = ["AEMET_API_KEY", "SOCIB_API_KEY", "COPERNICUS_USERNAME", "COPERNICUS_PASSWORD"]
}
variable "tags" {
  type    = map(string)
  default = { Project = "PredSea", ManagedBy = "Terraform", Environment = "migration" }
}
