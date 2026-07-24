# Dependency and image upgrades

Société pins versions intentionally. Do not use floating `:latest` tags.

## Docker Compose images

Defined in `.env.example` / `docker-compose.yml`:

| Service | Current pin |
|---------|-------------|
| PostgreSQL + PostGIS | `postgis/postgis:16-3.5` (`platform: linux/amd64`; official image is amd64-only) |
| Valkey | `valkey/valkey:8.1.9` |
| MinIO | `minio/minio:RELEASE.2025-09-07T16-13-09Z` |
| Mailpit | `axllent/mailpit:v1.30.5` |
| API base Python | `python:3.12.13-slim-bookworm` |
| uv (Docker) | `ghcr.io/astral-sh/uv:0.11.32` |

### Upgrade procedure

1. Choose an explicit tag from the upstream registry (Docker Hub / GHCR).
2. Update `.env.example`, `docker-compose.yml` defaults, `docs/dependency-upgrades.md`,
   and CI service images in `.github/workflows/ci.yml`.
3. Run `make dev-down && make dev-up`, then `make migrate`, `make test`.
4. Note any breaking changes in an ADR if behavior changes.

## Python

Managed by the root uv workspace (`pyproject.toml` + `uv.lock`).

```bash
uv lock --upgrade-package fastapi
uv sync
make test
```

## JavaScript / Expo

Node **24** is required (`.nvmrc`). Expo SDK packages must be installed with
`npx expo install` so they stay aligned with SDK 57. Non-Expo packages use
`pnpm add`.

```bash
cd apps/mobile
npx expo install expo@^57.0.0
pnpm add <package>
```

## Terraform providers

Pinned in `infra/terraform/environments/dev/main.tf`. Run
`make terraform-validate` after bumps. Never apply from Phase 0.
