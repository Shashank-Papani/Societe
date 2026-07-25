# Phase 3 stub — structure only. Do not apply; Phase 6 owns real buckets.

variable "environment" {
  type        = string
  description = "Environment name used in stub output names"
}

output "quarantine_bucket_name" {
  value       = "societe-${var.environment}-quarantine-stub"
  description = "Placeholder quarantine bucket name (not provisioned)"
}

output "processed_bucket_name" {
  value       = "societe-${var.environment}-processed-stub"
  description = "Placeholder processed-derivatives bucket name (not provisioned)"
}

output "phase3_status" {
  value       = "scaffold-only"
  description = "Phase 3 media_buckets stub — no AWS resources managed"
}
