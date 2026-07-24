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
make seed
make test
```

## Endpoints

- Liveness: `GET http://localhost:8000/health/live`
- Readiness: `GET http://localhost:8000/health/ready`
- Local JWT (dev only): `POST http://localhost:8000/v1/auth/local/token`
- Profile: `GET http://localhost:8000/v1/me` with `Authorization: Bearer …`
- Map venues: `GET http://localhost:8000/v1/map/venues?latitude=…&longitude=…`
- Venue detail: `GET http://localhost:8000/v1/venues/{id}`
- Mailpit UI: http://localhost:8025
- MinIO API: http://localhost:9000

## Auth guard

`AUTH_PROVIDER=local` is rejected at startup when `APP_ENV` is `staging` or
`production`. The local token endpoint never accepts arbitrary credentials;
subject/handle come from server configuration.

`GET /v1/me` returns the durable user profile (no `auth_subject`). Cognito claim
validation is implemented behind `AUTH_PROVIDER=cognito` but Cognito is not
deployed in Phase 1.

## Mobile

```bash
cd apps/mobile
pnpm start
```

Tabs: Discover (synthetic LA venue list via `DevelopmentMapProvider`) and Profile
(local JWT sign-in). Venue detail opens from a card.
