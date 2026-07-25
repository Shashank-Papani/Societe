# Phase 3 stub — MediaConvert seam for production video. Do not apply.

variable "environment" {
  type        = string
  description = "Environment name used in stub output names"
}

output "queue_arn" {
  value       = "arn:aws:mediaconvert:us-west-2:000000000000:queues/societe-${var.environment}-stub"
  description = "Placeholder MediaConvert queue ARN (not provisioned)"
}

output "role_arn" {
  value       = "arn:aws:iam::000000000000:role/societe-${var.environment}-mediaconvert-stub"
  description = "Placeholder MediaConvert IAM role ARN (not provisioned)"
}

output "phase3_status" {
  value       = "scaffold-only"
  description = "Phase 3 mediaconvert stub — no AWS resources managed"
}
