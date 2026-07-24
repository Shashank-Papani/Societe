# Société Terraform

Phase 0 includes module directory scaffolding and a `dev` environment that
passes `terraform validate` without creating AWS resources.

## Rules

- Never run `terraform apply` from Phase 0 automation.
- Never commit credentials, account IDs bound to production, or real tfvars secrets.
- Use OIDC CI roles in later phases; no long-lived access keys in the repo.

## Validate locally

```bash
make terraform-validate
```
