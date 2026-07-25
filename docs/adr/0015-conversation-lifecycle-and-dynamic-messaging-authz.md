# ADR 0015: Conversation lifecycle and dynamic messaging authz

## Status

Accepted

## Context

Blocking a user must stop new messages immediately, but a temporary block (or
account suspension that is later lifted) must not permanently destroy the
conversation or prevent messaging after a new valid connection exists.

## Decision

1. Conversations are retained permanently for the canonical user pair
   (`UNIQUE(user_low_id, user_high_id)`).
2. Do **not** set `conversations.revoked_at` on user block. Blocks are transient
   relative to conversation identity.
3. Send authorization is evaluated dynamically on every write from:
   - authenticated active account,
   - conversation membership,
   - active connection grant (`revoked_at IS NULL`),
   - mutual block state,
   - body/rate/abuse checks.
4. On block (or grant revoke that disables messaging), emit
   `conversation.messaging_disabled` for both participants when a conversation
   exists. On unblock or creation of a new active grant for the same pair, emit
   `conversation.messaging_enabled` if a conversation exists.
5. `conversations.revoked_at` is reserved for explicit permanent conversation
   closure (not used by Phase 5 block flows). If set in the future, messaging
   authz must clear or ignore it when a new active grant exists — Phase 5 send
   path treats an active grant + no block as sufficient even if a stale
   `revoked_at` were present (and clears `revoked_at` on successful resume).

## Consequences

History stays intact across block/unblock. Clients learn via realtime to
refetch; REST remains authoritative for whether send is allowed.
