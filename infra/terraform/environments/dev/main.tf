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

# Module wiring arrives in Phase 6. Keep module directories present for structure.
