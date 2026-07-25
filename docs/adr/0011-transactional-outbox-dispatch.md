# ADR 0011: Transactional outbox dispatch

## Status

Accepted

## Context

Presence and media already write `app.outbox_events` in the same PostgreSQL
transaction as the business row. Nothing drained those rows. Calling Cards need
reliable fan-out to realtime (and push fallback) without dual-writes.

## Decision

1. Keep the existing `outbox_events` table as the sole publish queue.
2. Add `event_dispatcher` worker that claims with `FOR UPDATE SKIP LOCKED`,
   publishes via `RealtimePublisher`, then sets `published_at`.
3. Retries use exponential backoff with jitter; `attempt_count` and `last_error`
   are updated on failure. Never mark published before provider success.
4. Consumers treat delivery as at-least-once; event `id` is the dedupe key.
5. Private fields (precise location, evidence) are never placed in outbox
   payloads. Trace ids propagate when present.
6. Compose health uses a heartbeat file, matching `media_processor`.

## Consequences

Realtime and push are side effects of committed outbox rows. REST remains the
source of truth; missed events are healed by client refetch.
