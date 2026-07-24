# Société API

Phase 1 FastAPI modular monolith: identity, venues, and Discover map.

Local (outside Compose):

```bash
uv run --directory services/api uvicorn app.main:app --reload --port 8000
```

With Compose, the `api` service is started by `make dev-up`.

## Phase 1 routes

| Method | Path | Notes |
|--------|------|-------|
| POST | `/v1/auth/local/token` | Dev/test local JWT only |
| GET | `/v1/me` | Profile (no auth_subject) |
| PATCH | `/v1/me` | Optional Idempotency-Key |
| PATCH | `/v1/me/privacy` | Optional Idempotency-Key |
| POST | `/v1/me/devices` | Requires Idempotency-Key |
| DELETE | `/v1/me/devices/{id}` | Optional Idempotency-Key |
| POST | `/v1/me/account-deletion` | Requires Idempotency-Key |
| GET | `/v1/map/venues` | Authoritative PostGIS nearby |
| GET | `/v1/venues/{id}` | Public detail (no security geometry) |
