# location_aggregator

Presence lease expiry and location-evidence retention worker.

It imports `app.modules.presence.service.PresenceService` directly rather than
calling the API over HTTP, so expiry semantics cannot drift from the request
path.

## Cycles

| Cycle  | Interval | Work                                                                 |
| ------ | -------- | -------------------------------------------------------------------- |
| expire | 30s      | `verified → degraded` past `verified_until`, `→ exited` past `grace_until`, then clear the Valkey lease |
| purge  | 15m      | delete `ephemeral.location_evidence` rows past `purge_at`             |

Both use bounded batches with `FOR UPDATE SKIP LOCKED`, so multiple replicas can
run concurrently without contending on the same rows.

## Run locally

```bash
set -a && . ./.env && set +a
PYTHONPATH=services/workers uv run python -m location_aggregator
```

Under Compose it runs as the `location-aggregator` service from the API image.
