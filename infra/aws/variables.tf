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
variable "ww3_image_digest" {
  type        = string
  description = "Immutable ECR digest for the WW3 AWS Batch image"
  default     = "sha256:6ad5b323114b0f0bced2b1c434e4143d48e8519ed8574cb361ee671daa8f78db"
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.ww3_image_digest))
    error_message = "ww3_image_digest must be a sha256 digest."
  }
}
variable "batch_instance_types" {
  type        = list(string)
  description = "128-vCPU x86_64 compute-optimized instance types available to AWS Batch"
  default     = ["c6i.32xlarge"]
  validation {
    condition     = length(var.batch_instance_types) > 0 && alltrue([for instance_type in var.batch_instance_types : instance_type == "c6i.32xlarge"])
    error_message = "batch_instance_types must contain only the approved 128-vCPU type: c6i.32xlarge."
  }
}
variable "batch_root_volume_size_gib" {
  type        = number
  description = "Encrypted gp3 root volume size for ephemeral Batch compute nodes"
  default     = 300
  validation {
    condition     = var.batch_root_volume_size_gib >= 50
    error_message = "batch_root_volume_size_gib must be at least 50 GiB."
  }
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
