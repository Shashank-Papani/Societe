# ADR 0004 — AppSync Events for realtime; REST for commands

## Status

Accepted

## Context

Clients need low-latency inbox and presence updates without accepting sensitive
commands over WebSockets.

## Decision

Use AWS AppSync Events for authorized private channels. All mutating business
commands (Calling Cards, blocks, presence evidence) go through authenticated
REST. A transactional outbox drives event publication.

## Consequences

Realtime is delivery, not durable state. Local Phase 0 does not stand up
AppSync; adapters arrive in later phases.
