output "bucket" { value = aws_s3_bucket.outputs.id }
output "ecr_repositories" { value = { for k, v in aws_ecr_repository.repos : k => v.repository_url } }
output "ecs_cluster" { value = aws_ecs_cluster.predsea.name }
output "orchestrator_task_definition" { value = aws_ecs_task_definition.orchestrator.arn }
output "simulation_instance_profile" { value = aws_iam_instance_profile.simulation.name }
output "api_url" { value = var.create_api_service ? aws_apprunner_service.api[0].service_url : "" }
output "secret_arns" { value = { for k, v in aws_secretsmanager_secret.predsea : k => v.arn } }
output "codebuild_project" { value = aws_codebuild_project.images.name }
