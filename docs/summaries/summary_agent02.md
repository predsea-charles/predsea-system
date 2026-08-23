Executive Summary
The repository-defined AWS architecture is not safe for deployment in its current form. The most serious issue is a plaintext AWS access key file that would be copied into the CodeBuild source archive and API/orchestrator images.
The audit also found excessive IAM permissions, public-by-default networking, incomplete orphan cleanup, duplicate-execution risks, mutable runtime artifacts, and missing cost controls.
No live AWS state was queried. Consequently, the resources actually deployed cannot be verified.
Actual AWS Architecture
Terraform defines:
- One encrypted, versioned S3 bucket.
- Five ECR repositories.
- Four Secrets Manager containers.
- Athena workgroup and Glue table.
- ECS Fargate orchestration task.
- Disabled-by-default EventBridge Scheduler schedule.
- One App Runner API service.
- CodeBuild image builder.
- IAM roles for ECS, EC2, Scheduler, App Runner, and CodeBuild.
- API and orchestrator CloudWatch log groups.
The orchestrator launches one c6i.32xlarge Spot worker with an encrypted 300 GB gp3 root volume and IMDSv2. That instance executes WRF, five sequential CROCO runs, and five sequential WW3 runs.
Evidence: [main.tf](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf), [aws_orchestrator.py](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py), [variables.tf](/Users/charles.santana/PredSea/predsea-system/infra/aws/variables.tf).
No Terraform state or backend configuration exists in infra/aws, so repository evidence does not establish which resources currently exist.
Documentation vs Infrastructure
- EventBridge is implemented, not merely documented. Its default is DISABLED, but callers can override it through schedule_state: [variables.tf (line 17)](/Users/charles.santana/PredSea/predsea-system/infra/aws/variables.tf:17), [main.tf (line 294)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:294).
- The documentation says console output is streamed, but the task role lacks ec2:GetConsoleOutput; the resulting authorization error is silently ignored: [aws_orchestrator.py (line 164)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:164), [main.tf (line 166)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:166).
- IAM roles are nominally separate, but the ECS task, EC2 worker, and App Runner API receive the same runtime policy: [main.tf (line 142)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:142), [main.tf (line 158)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:158), [main.tf (line 235)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:235).
- The documentation advises avoiding committed credentials, but the checkout contains plaintext AWS credentials.
- Production and migration infrastructure are not separated. Resources have fixed shared names, default tags say Environment=migration, while App Runner receives PREDSEA_ENV=prod: [variables.tf (line 81)](/Users/charles.santana/PredSea/predsea-system/infra/aws/variables.tf:81), [main.tf (line 249)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:249).
Security Findings
AWS-SEC-001 — CRITICAL — Plaintext AWS credentials enter build artifacts
- File: aws_credentials.txt, lines 6–7.
- Current behavior: The file contains access-key and secret-key fields and matches an AWS access-key pattern.
- Evidence: No .dockerignore exists. [Dockerfile.aws (line 12)](/Users/charles.santana/PredSea/predsea-system/Dockerfile.aws:12) copies the entire repository. [deploy_aws.sh (line 20)](/Users/charles.santana/PredSea/predsea-system/deploy_aws.sh:20) archives the repository without excluding this file, then uploads it to S3 at line 23.
- Risk: Credentials can be exposed through S3 source archives, CodeBuild workspaces, image layers, ECR images, or anyone with checkout access.
- Recommended action: Revoke/rotate the credentials immediately; investigate use; remove them from repository history and existing S3/ECR/CodeBuild artifacts; add explicit ignore and secret-scanning controls.
AWS-SEC-002 — HIGH — Orchestrator can terminate unrelated EC2 instances
- File: [main.tf (line 166)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:166).
- Current behavior: The ECS task role receives ec2:TerminateInstances over Resource="*" without a tag condition.
- Risk: Compromise or coding error could terminate unrelated account instances.
- Recommended action: Constrain instance type, subnet, profile, required request/resource tags, and termination permissions.
AWS-SEC-003 — MEDIUM — Shared runtime policy violates least privilege
- File: [main.tf (line 142)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:142).
- Current behavior: App Runner, ECS, and EC2 all receive S3 write, all PredSea secret reads, Athena, Glue, and model-image ECR permissions.
- Risk: The public API can access secrets and capabilities it does not evidently require.
- Recommended action: Create narrowly scoped, component-specific policies.
AWS-SEC-004 — MEDIUM — Public/default networking
- File: [variables.tf (line 61)](/Users/charles.santana/PredSea/predsea-system/infra/aws/variables.tf:61), [main.tf (line 2)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:2).
- Current behavior: Default-VPC subnets are used, public IP assignment defaults to true, and no security group is created.
- Risk: Workloads depend on uncontrolled default-VPC settings and receive unnecessary public addressing.
- Recommended action: Define reviewed networking and explicit egress-only security groups.
AWS-SEC-005 — MEDIUM — Mutable and non-reproducible runtime
- Evidence: ECR tags are mutable at [main.tf (line 43)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:43); image defaults are latest at [variables.tf (line 45)](/Users/charles.santana/PredSea/predsea-system/infra/aws/variables.tf:45); the worker selects the newest matching AMI and installs packages during boot at [aws_orchestrator.py (line 56)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:56) and [aws_orchestrator.py (line 177)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:177).
- Risk: Identically named runs can execute different software.
- Recommended action: Pin image digests, AMI IDs, and pre-bake worker dependencies.
Reliability Findings
AWS-REL-001 — HIGH — Cleanup is not guaranteed
The exit trap normally uploads diagnostics and terminates the worker: [aws_orchestrator.py (line 46)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:46). It cannot protect against failure before user data starts, abrupt Spot termination, or loss of the supervising Fargate task. There is no independent janitor or TTL cleanup.
Risk: Running EC2 instances and associated costs can be orphaned.
AWS-REL-002 — HIGH — Duplicate execution is possible
RunInstances has no idempotency ClientToken: [aws_orchestrator.py (line 129)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:129). Run IDs have minute resolution, and there is no S3/DynamoDB lock or existing-run check.
Risk: Retries or concurrent invocations can launch duplicate expensive workers and overwrite shared status paths.
AWS-REL-003 — MEDIUM — Scheduler does not supervise task completion
The Scheduler target only starts an ECS task: [main.tf (line 294)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:294). No dead-letter queue, explicit retry policy, alarm, or independent run monitor is defined.
AWS-REL-004 — MEDIUM — Diagnostic publication is best-effort
Failure uploads use || true, followed by termination: [aws_orchestrator.py (line 50)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:50). An S3 outage can therefore leave neither status nor diagnostic logs.
AWS-REL-005 — MEDIUM — Partial and complete data share prefixes
WRF and regional outputs are uploaded incrementally before the final SIMULATION_STATUS.json. Consumers must always verify completion markers; Terraform does not enforce this contract.
Cost Findings
AWS-COST-001 — HIGH — Current S3 objects never expire
The lifecycle rule expires only noncurrent versions and incomplete multipart uploads: [main.tf (line 32)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:32). Forecasts, forcing, logs, Athena results, and CodeBuild source archives can accumulate indefinitely.
AWS-COST-002 — MEDIUM — Athena has no scan limit
The workgroup enforces configuration but defines no bytes-scanned cutoff: [main.tf (line 62)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:62).
AWS-COST-003 — MEDIUM — Orphaned EC2 remains possible
There is no external maximum-age termination mechanism, budget alarm, or EC2 cleanup schedule.
AWS-COST-004 — LOW — Logging retention is incomplete
The Terraform-managed API log group appears unused by App Runner. CodeBuild uses /predsea/codebuild, but that group is not Terraform-managed and has no configured retention: [main.tf (line 189)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:189).
Orphan/Cleanup Risks
- EC2 worker survives if both user-data cleanup and the Fargate supervisor fail.
- No tagged-instance janitor exists.
- No stale-run lock cleanup exists.
- Current S3 objects and Athena results have no expiration.
- Versioning increases storage after overwrites.
- Source archives remain in the same long-lived bucket.
- EBS is correctly encrypted and marked DeleteOnTermination, but deletion still depends on instance termination.
Findings
ID	Severity	Summary
AWS-SEC-001	CRITICAL	Plaintext AWS credentials enter S3 and container build contexts
AWS-SEC-002	HIGH	ECS task can terminate any EC2 instance
AWS-REL-001	HIGH	No guaranteed independent EC2 cleanup
AWS-REL-002	HIGH	No launch idempotency or run locking
AWS-COST-001	HIGH	Current S3 data has no expiration
AWS-SEC-003	MEDIUM	Shared over-privileged runtime policy
AWS-SEC-004	MEDIUM	Public/default networking
AWS-SEC-005	MEDIUM	Mutable images and runtime dependencies
AWS-REL-003–005	MEDIUM	Monitoring, diagnostics, and partial-output weaknesses
AWS-COST-002–003	MEDIUM	Athena and orphan cost exposure
AWS-COST-004	LOW	Incomplete log retention management


Unknowns
- Which Terraform resources, if any, currently exist.
- Whether EventBridge has been overridden to ENABLED.
- Whether the exposed AWS key is active or has been used.
- Current bucket policies, ACLs, VPC defaults, quotas, budgets, alarms, and resources created outside Terraform.
- Existing S3/ECR/CodeBuild copies of the credentials file.
- Actual Spot interruption and end-to-end recovery behavior.
Recommended Next Steps
1. Revoke and investigate the exposed AWS credentials before any build or deployment.
2. Inventory live AWS resources using a separately secured read-only audit role.
3. Prevent credentials from entering source archives and images.
4. Restrict IAM and define explicit networking.
5. Add idempotent launches, run locks, independent worker cleanup, alarms, and DLQ handling.
6. Add S3 retention and Athena scan-cost controls.
7. Pin immutable images and AMIs.
8. Keep EventBridge disabled until these controls and a reviewed manual run pass.
STATUS:
FAIL
FINDINGS:
One critical, four high, multiple medium, and two low-severity infrastructure findings.
EVIDENCE:
Repository Terraform, orchestration, deployment, Docker, and mocked-test definitions were inspected with line-level references. Secret values were not disclosed.
RISKS:
Credential compromise, termination of unrelated instances, duplicate expensive workers, orphan resources, uncontrolled storage/query growth, and irreproducible execution.
UNKNOWN:
Live AWS state was not queried; deployed resources and credential activity remain unverified.
CHANGES MADE:
None.
TESTS RUN:
Read-only static inspection completed. tests/aws could not run because pytest is not installed. Terraform tooling is not installed. No AWS API or workload was invoked.
AWS / COST IMPACT:
None. No Terraform actions, deployments, AWS API calls, EC2 launches, or paid workloads were performed.
RECOMMENDED NEXT STEP:
Rotate the exposed credentials and perform a read-only live-resource inventory before any deployment.


1:07 PM
