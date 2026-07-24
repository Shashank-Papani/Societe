# Société

Real-time nightlife discovery and in-venue social connection.

This repository is the Societe monorepo. The authoritative architecture lives in
[`docs/societe_cursor_master_architecture.md`](docs/societe_cursor_master_architecture.md).

## Phase 0 status

Foundation only:

- FastAPI modular monolith skeleton
- Docker Compose: PostGIS 16, Valkey 8, MinIO, Mailpit, API
- Alembic baseline (extensions + schemas)
- Structured logging, request IDs, OpenTelemetry foundation
- Local-development JWT auth (blocked outside development/test)
- Expo SDK 57 mobile skeleton
- CI, ADRs, Terraform validate scaffolding

Not included yet: venues, map, presence, Calling Cards, Live Vibes, Cognito,
AppSync, or AWS deployment.

## Quick start

```bash
# Use Node 24
fnm use   # or: nvm use

make bootstrap
make dev-up
make migrate
curl -s http://localhost:8000/health/live | jq
curl -s http://localhost:8000/health/ready | jq
make test
```

Mobile:

```bash
cd apps/mobile && pnpm start
```

## Make targets

| Target | Purpose |
|--------|---------|
| `make bootstrap` | Install deps + create `.env` |
| `make dev-up` | Start Compose stack |
| `make dev-down` | Stop containers (keeps volumes) |
| `make migrate` | Alembic upgrade |
| `make test` / `lint` / `typecheck` | Quality gates |
| `make clean` | Caches only (not Docker volumes) |
| `make reset-local-data` | **Destructive** volume wipe |

## Security notes

- Never commit `.env` or JWT secrets
- `AUTH_PROVIDER=local` cannot run when `APP_ENV` is staging/production
- Do not push secrets or production credentials
