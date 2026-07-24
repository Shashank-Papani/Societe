# Local development

## Prerequisites

- Docker Desktop running
- Node 24 (`fnm use` / `nvm use` — see `.nvmrc`)
- pnpm, uv, watchman
- Python 3.12 (via uv)

## First run

```bash
cd "/Users/shashankpapani/Coding/Personal Projects/Societe/Societe"
make bootstrap
make dev-up
make migrate
make test
```

## Endpoints

- Liveness: `GET http://localhost:8000/health/live`
- Readiness: `GET http://localhost:8000/health/ready`
- Local JWT (dev only): `POST http://localhost:8000/v1/auth/local/token`
- Current principal: `GET http://localhost:8000/v1/me` with `Authorization: Bearer …`
- Mailpit UI: http://localhost:8025
- MinIO API: http://localhost:9000

## Auth guard

`AUTH_PROVIDER=local` is rejected at startup when `APP_ENV` is `staging` or
`production`. The local token endpoint never accepts arbitrary credentials;
subject/handle come from server configuration.

## Mobile

```bash
cd apps/mobile
pnpm start
```

Use the local token endpoint and store the JWT via SecureStore (Phase 0 login
screen).
