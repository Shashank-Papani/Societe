# ADR 0017: Read state and unread strategy

## Status

Accepted

## Context

Unread badges and read receipts must stay correct under concurrent message
delivery and duplicate read requests.

## Decision

1. Per-member state lives on `conversation_members`: `last_read_message_id`,
   `last_read_at`, denormalized `unread_count`.
2. Read advances monotonically: the target message must belong to the
   conversation; if it is older than or equal to the current
   `last_read_message_id` (by `(created_at, id)`), the request is a no-op
   success (or ignored) and never moves backward.
3. On `message.created`, increment the non-sender member’s `unread_count` in
   the same transaction.
4. On successful forward read, set `last_read_message_id` / `last_read_at` and
   recompute `unread_count` as the count of messages after that watermark
   (excluding the reader’s own messages, excluding deleted-only tombstones
   still counts as “seen” once past them).
5. Opening a conversation triggers mark-as-read for the latest visible message.

## Consequences

Unread is authoritative on the server. Clients may optimistically clear badges
but must refetch after realtime `message.read` / `message.created`.
