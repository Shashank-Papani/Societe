# Phase 5 implementation plan — Private messaging

Phase 4 Calling Cards and realtime are complete. Phase 5 adds private
one-to-one messaging on top of accepted `connection_grants`.

Out of scope: media messages, typing, online presence, reactions, edit API,
disappearing messages, groups, E2E encryption, App Attest/QR/BLE (architecture
§25 “Phase 5 Safety” is deferred; product Phase 5 is messaging), terraform
apply, AWS deploy.

## Corrections from approval

1. **Durable grants for messaging.** Accepted `connection_grants` are not
   terminated by venue exit or the venue-night 06:00 boundary. Messaging uses
   `revoked_at` (plus blocks and account status) as the primary termination
   condition. See ADR 0014.
2. **No permanent conversation kill on block.** Conversations persist. Send
   authz is dynamic. Block emits `conversation.messaging_disabled`; resume is
   allowed after unblock or a new valid grant. See ADR 0015.
3. **`client_message_id` is the durable dedupe key.**
   `UNIQUE(sender_user_id, client_message_id)`. `Idempotency-Key` must equal
   `client_message_id` when present (or may be omitted and derived from it).
4. **Two members atomically in the service transaction** (not a SQL CHECK).
5. **No message bodies** in logs, traces, outbox, WebSocket, or push.
6. **Monotonic read state** with atomic unread updates.

## 1. Contracts (`/v1`)

```text
POST /conversations
GET  /conversations
GET  /conversations/{id}
GET  /conversations/{id}/messages
POST /conversations/{id}/messages
POST /conversations/{id}/read
POST /conversations/{id}/archive
POST /conversations/{id}/unarchive
```

REST is authoritative. Realtime only notifies clients to refetch.

## 2. Database (migration `0006`)

- Make `connection_grants.expires_at` nullable; null = durable for messaging.
- Backfill non-revoked grants: `expires_at = NULL`.
- Accept path writes `expires_at = NULL`.
- `conversations`, `conversation_members`, `messages` as specified in
  requirements (with soft-delete fields; no edit API).

## 3. Authorization

Before send/create: active account, participant, active grant
(`revoked_at IS NULL`; `expires_at` null or ignored for messaging), no mutual
block, body/rate limits. No venue lease required.

## 4. Outbox events

`conversation.created`, `conversation.archived`, `conversation.messaging_disabled`,
`conversation.messaging_enabled`, `message.created`, `message.read`.

Payloads: identifiers only (+ optional non-body metadata). No full bodies.

## 5. Mobile

Messages entry in Connect → list → thread. Offline queue op `message.send`
with `client_message_id` generated before SQLite insert. Shared realtime
client with `event_id` dedupe.

## 6. Quality gates

Full suite from Phase 5 requirements. No commit/tag/push/terraform apply.
