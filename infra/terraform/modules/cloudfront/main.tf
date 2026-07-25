# Phase 3 stub — signed CloudFront distribution for derivatives. Do not apply.

variable "environment" {
  type        = string
  description = "Environment name used in stub output names"
}

output "distribution_domain" {
  value       = "societe-${var.environment}-media.example.invalid"
  description = "Placeholder CloudFront domain (not provisioned)"
}

output "phase3_status" {
  value       = "scaffold-only"
  description = "Phase 3 cloudfront stub — no AWS resources managed"
}
