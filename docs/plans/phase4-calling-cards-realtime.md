# Phase 4 implementation plan — Calling Cards and realtime

Gate A (Phase 3 gallery upload) is complete: real JPEG → intent → PUT →
process → moderate → publish → Echo Basement feed. Phase 4 builds private
same-venue social discovery and Calling Cards on top of verified presence.

Out of scope: DMs, comments, likes, QR/BLE/Wi-Fi proofs, App Attest, Play
Integrity, crowd demographics, visual redesign, terraform apply, AWS deploy.

## 1. Contracts (`/v1`)

```text
GET  /venues/me/discoverable-users     same-venue discovery (venue from lease)
POST /calling-cards                    create (Idempotency-Key required)
GET  /calling-cards/inbox              recipient pending/recent
GET  /calling-cards/sent               sender recent
GET  /calling-cards/{id}               detail
POST /calling-cards/{id}/respond       accept | decline (Idempotency-Key)
POST /calling-cards/{id}/cancel        sender cancel
POST /calling-cards/{id}/share         update share scopes after accept
GET  /calling-cards/{id}/status        lightweight status poll
POST /users/{user_id}/block            block (cancels cards, revokes grants)
DELETE /users/{user_id}/block          unblock
```

REST remains authoritative. Realtime only notifies clients to refetch.

## 2. Database (migration `0005`)

- `app.user_blocks` — pair uniqueness, created_at
- `app.calling_cards` — architecture DDL (pair_low/high, statuses, indexes)
- `app.connection_grants` — one accepted card, scopes JSONB, revoke fields
- Outbox already exists; dispatcher claims unpublished rows

## 3. Authorization

`SocialService.authorize_calling_card_send` follows architecture §14 order.
Mirror `PresenceService.can_post_live_vibe` lease reads but require:

- Ghost off, discoverable on, `allow_calling_cards` for **both** users
- mutual verified leases at the **same** venue
- durable check-ins active
- no blocks, no pending pair card, decline cooldown, rate limits

Accept re-runs presence/privacy/block checks; exit → fail closed.

## 4. Discovery

Venue is taken only from the caller's Valkey lease. List members of
`presence:venue:{id}:discoverable`, hydrate privacy-safe cards, exclude ghost,
blocked, self, and non-matching leases. Coarse cache TTL in Valkey optional.

## 5. Outbox dispatcher

`services/workers/event_dispatcher`: SKIP LOCKED claim, exponential backoff +
jitter, `published_at` after provider ack, dedupe by event id, health heartbeat.
Local realtime adapter first; AppSync adapter interface + Terraform stub only.

## 6. Realtime + push

- `RealtimePublisher` Protocol: local WebSocket server in Compose; AppSync stub
- `PushPublisher` Protocol: local log/test adapter; no APNs/FCM secrets
- Integration test: no realtime ack → push fallback requested

## 7. Mobile Connect

New Connect tab: discoverable list, send with reason, inbox/sent, accept/decline/
cancel, share scopes, expiry countdown, Ghost/blocked/exited empty states.
expo-sqlite offline command queue with idempotency key preservation.

## 8. Fixtures

Dev helpers for two synthetic users verified at Echo Basement (simulator /
seed). Do not weaken production authz.

## 9. Quality gates

Full suite from the Phase 4 brief §14. No claim of success with failures.
