# ADR 0016: Message idempotency via client_message_id

## Status

Accepted

## Context

Offline retries and flaky nightlife networks must not create duplicate messages.
Phase 4 used a separate HTTP `Idempotency-Key` for Calling Cards. For messages,
two unrelated identifiers invite client bugs.

## Decision

1. Durable dedupe key is `UNIQUE(sender_user_id, client_message_id)`.
2. The mobile client generates `client_message_id` (UUID) **before** enqueueing
   the SQLite offline operation and reuses it on every retry.
3. HTTP `Idempotency-Key`, when supplied, **must equal** `client_message_id`.
   If omitted, the API treats `client_message_id` as the idempotency key for
   the shared `IdempotencyService` record.
4. Retries return the original authoritative message row (same id and
   timestamps). Never invent a second server message for the same pair.

## Consequences

One logical send has one client id for the life of the operation. REST
idempotency storage and the database unique constraint stay aligned.
