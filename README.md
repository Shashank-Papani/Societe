# Société

Real-time nightlife discovery and in-venue social connection.

This repository is the Societe monorepo. The authoritative architecture lives in
[`docs/societe_cursor_master_architecture.md`](docs/societe_cursor_master_architecture.md).

## Phase 1 status

Identity, venue catalog, and Discover map:

- Cognito-compatible identity interface + local JWT auth
- Users, privacy settings, devices (no push tokens)
- Soft account deletion with idempotent replay
- Venues + hours with PostGIS nearby query
- Static Valkey card hydration (`venue:static:v1:{id}`)
- Signed map cursors and map filters
- Synthetic LA seed data
- Expo Discover / Profile / venue detail with `DevelopmentMapProvider`

Not included yet: presence/geofencing, Calling Cards, Live Vibes, Mapbox SDK,
H3 acceleration, AppSync, or AWS deployment.

## Quick start

```bash
# Use Node 24
fnm use   # or: nvm use

make bootstrap
make dev-up
make migrate
make seed
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
| `make seed` | Synthetic LA venues + users |
| `make test` / `lint` / `typecheck` | Quality gates |
| `make clean` | Caches only (not Docker volumes) |
| `make reset-local-data` | **Destructive** volume wipe |

## Security notes

- Never commit `.env` or JWT secrets
- `AUTH_PROVIDER=local` cannot run when `APP_ENV` is staging/production
- Do not push secrets or production credentials
- Location query fields are redacted from logs by field name
