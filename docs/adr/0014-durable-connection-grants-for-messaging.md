# ADR 0014: Durable connection grants for messaging

## Status

Accepted

## Context

Phase 4 set `connection_grants.expires_at` to the next venue-local 06:00
boundary. That matched same-night Calling Card share scopes, but it would
disable messaging after night end even when neither party blocked or revoked
the connection. Product requirement: once a Calling Card is accepted,
messaging remains available until block, explicit revoke, account
suspension/deletion, or another documented safety policy.

## Decision

1. Keep using `app.connection_grants` (no separate friendship table).
2. Treat `revoked_at IS NULL` as the primary “connection is alive” signal for
   messaging authorization.
3. Make `expires_at` nullable. `NULL` means the grant is durable for messaging
   (not bound to venue night).
4. On Calling Card accept, write `expires_at = NULL`.
5. Migration backfills existing non-revoked grants to `expires_at = NULL`.
6. Messaging authz does **not** require a current venue lease and does **not**
   treat venue-night 06:00 as termination.
7. Leaving the venue never revokes a grant.

## Consequences

Accepted connections survive overnight and after exit. Block and explicit
revoke remain the operational off-switches. Future safety policies may set
`revoked_at` with a documented reason without inventing a parallel graph.
