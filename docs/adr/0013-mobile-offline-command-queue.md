# ADR 0013: Mobile offline command queue

## Status

Accepted

## Context

Nightlife networks drop. Calling Card creates/responds must not lose the
Idempotency-Key or invent a second key on retry. SQLite already ships with the
Expo app (`expo-sqlite`).

## Decision

1. Persist outbound social commands in expo-sqlite with: local op id, server
   idempotency key, type, sanitized payload, timestamps, attempts, next attempt,
   last error category, terminal state.
2. Retry only timeouts, 429, and retryable 5xx. Honor `Retry-After`. Use
   exponential backoff with jitter.
3. Never retry permanent 4xx. Never send after business `expires_at`.
4. Never store auth tokens, precise coordinates, or location evidence in SQLite.
5. UI states: queued → sending → server_pending → delivered / accepted /
   declined / expired / failed_*. Never show “Sent” before the server commits.

## Consequences

Connect UI and the queue share one idempotency key per logical operation for the
lifetime of the command.
