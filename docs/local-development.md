# Local development

## Prerequisites

- Docker Desktop running
- Node 24 (`fnm use` / `nvm use` — see `.nvmrc`)
- pnpm, uv, watchman
- Python 3.12 (via uv)

## First run

```bash
cd "/Users/shashankpapani/Coding/Projects/Societe"
make bootstrap
make dev-up
make migrate
make seed
make test
```

## Endpoints

- Liveness: `GET http://localhost:8000/health/live`
- Readiness: `GET http://localhost:8000/health/ready`
- Email OTP: `POST /v1/auth/otp/request`, `POST /v1/auth/otp/verify`
- Refresh / logout: `POST /v1/auth/refresh`, `POST /v1/auth/logout`
- Dev personas (dev/test only): `POST /v1/auth/local/token`
- Profile: `GET http://localhost:8000/v1/me`
- Map venues: `GET http://localhost:8000/v1/map/venues?latitude=…&longitude=…`
- Venue detail: `GET http://localhost:8000/v1/venues/{id}`
- Presence: `POST /v1/presence/evidence`, `GET /v1/presence/me`, `POST /v1/presence/leave`
- Dev simulator (flag): `POST /v1/dev/location/simulate`
- Mailpit UI: http://localhost:8025 (read OTP codes here)
- MinIO API: http://localhost:9000

## Auth guard

- `EMAIL_PROVIDER=mailpit` (or `memory`) is forbidden outside development/test.
- Staging/production require `EMAIL_PROVIDER=ses` and `SES_FROM_EMAIL`.
- Dev persona minting (`/v1/auth/local/token`) remains development/test only.
- `FF_LOCATION_SIMULATOR=true` is forbidden outside development/test.

## Mobile

```bash
cd apps/mobile
pnpm start
```

Auth gate routes unauthenticated users to email OTP. Incomplete onboarding opens
the onboarding wizard. Dev Alpha/Beta buttons appear only in `__DEV__`.
`AuthProvider` stores access + refresh tokens in SecureStore and retries once on
401 after refresh.
