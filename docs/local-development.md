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
- Profile: `GET http://localhost:8000/v1/me`
- Map venues: `GET http://localhost:8000/v1/map/venues?latitude=…&longitude=…`
- Venue detail: `GET http://localhost:8000/v1/venues/{id}`
- Presence: `POST /v1/presence/evidence`, `GET /v1/presence/me`, `POST /v1/presence/leave`
- Dev simulator (flag): `POST /v1/dev/location/simulate`
- Mailpit UI: http://localhost:8025
- MinIO API: http://localhost:9000

## Auth guard

`AUTH_PROVIDER=local` is rejected when `APP_ENV` is `staging` or `production`.

`FF_LOCATION_SIMULATOR=true` is likewise forbidden outside development/test.

## Mobile

```bash
cd apps/mobile
pnpm start
```

Tabs: Discover, Presence, Profile. Auth is centralized in `AuthProvider` so
Discover refetches after login without an app reload. Foreground location uses
Expo Location via `LocationProvider`.
