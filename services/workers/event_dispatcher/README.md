# event_dispatcher

Drains `app.outbox_events` with `FOR UPDATE SKIP LOCKED`, publishes via
`RealtimePublisher` to `user:{id}` channels, and sets `published_at` only after
provider success. Retries use exponential backoff with jitter on `available_at`.

## Local realtime (API-hosted WebSocket)

There is **no** separate `realtime_hub` Compose service. The API hosts:

- `WS /v1/realtime/ws` — Bearer-authenticated subscription to `user:{id}`
- `POST /v1/events/{event_id}/ack` — sets Valkey `realtime:ack:{event_id}`

`LocalRealtimeHub` fans out over Valkey pubsub so this worker (separate process)
and API WebSocket clients share the same local bus. Clients must deduplicate by
`event_id`.

After each successful realtime publish the worker waits
`REALTIME_ACK_WAIT_SECONDS`, then requests push fallback when the ack key is
missing. If realtime publish raises, push is attempted once and the outbox row
retries.

Local Compose uses `REALTIME_PROVIDER=local`. AppSync is an interface + Terraform
stub only — do not set `appsync` outside a later wiring phase.
