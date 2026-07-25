# Phase 0 Terraform scaffolding — validate only. Do not apply.
# Remote backend configuration is intentionally example-only.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
  }
}

provider "aws" {
  region                      = var.aws_region
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  access_key                  = "mock"
  secret_key                  = "mock"
}

variable "aws_region" {
  type        = string
  description = "AWS region for future environments"
  default     = "us-west-2"
}

variable "environment" {
  type        = string
  description = "Environment name"
  default     = "dev"
}

output "phase0_status" {
  value       = "scaffold-only"
  description = "Phase 0 placeholder — no resources managed yet"
}

# Phase 3 stubs: validate module shape only. Real wiring and apply are Phase 6.
module "media_buckets" {
  source      = "../../modules/media_buckets"
  environment = var.environment
}

module "mediaconvert" {
  source      = "../../modules/mediaconvert"
  environment = var.environment
}

module "media_cloudfront" {
  source      = "../../modules/cloudfront"
  environment = var.environment
}

output "phase3_media_status" {
  value = {
    media_buckets = module.media_buckets.phase3_status
    mediaconvert  = module.mediaconvert.phase3_status
    cloudfront    = module.media_cloudfront.phase3_status
  }
  description = "Phase 3 media Terraform stubs — validate only, never applied here"
}

# Phase 4 stub: AppSync Events shape only. Real wiring and apply are Phase 6.
module "appsync_events" {
  source      = "../../modules/appsync_events"
  environment = var.environment
}

output "phase4_realtime_status" {
  value = {
    appsync_events = module.appsync_events.phase4_status
    http_endpoint  = module.appsync_events.events_http_endpoint
  }
  description = "Phase 4 AppSync Events Terraform stub — validate only, never applied here"
}

# Remaining module wiring arrives in Phase 6. Keep module directories present for structure.
