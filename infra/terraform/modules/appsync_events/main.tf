# Phase 4 stub — structure only. Do not apply; Phase 6 owns real AppSync Events.

variable "environment" {
  type        = string
  description = "Environment name used in stub output names"
}

output "events_api_id" {
  value       = "societe-${var.environment}-appsync-events-stub"
  description = "Placeholder AppSync Events API id (not provisioned)"
}

output "events_http_endpoint" {
  value       = "https://appsync-events-stub.invalid/${var.environment}"
  description = "Placeholder AppSync Events HTTP endpoint (not provisioned)"
}

output "events_realtime_endpoint" {
  value       = "wss://appsync-events-stub.invalid/${var.environment}"
  description = "Placeholder AppSync Events realtime endpoint (not provisioned)"
}

output "phase4_status" {
  value       = "scaffold-only"
  description = "Phase 4 appsync_events stub — no AWS resources managed"
}
