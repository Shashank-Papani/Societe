# ADR 0010: Calling Card authorization and expiration

## Status

Accepted

## Context

Calling Cards are sensitive, same-venue social requests. A stale lease, Ghost
Mode, or a cross-venue pair must never produce a durable pending card. Acceptance
after either party exits must not create a connection grant.

## Decision

1. Authorization follows the ordered checklist in the master architecture §14.
2. Venue identity always comes from fresh Valkey leases, never from a
   client-supplied venue id on create/discover.
3. Ghost Mode, `discoverable_in_venue=false`, and `allow_calling_cards=false`
   block send **and** receive. (Unlike Live Vibe posting.)
4. Cards expire at `min(created_at + CALLING_CARD_TTL, next venue-local 06:00)`.
   Default TTL is short for nightlife (configurable; initial 30 minutes).
5. Accept revalidates both leases, blocks, privacy, and durable check-ins in one
   transaction with grant + outbox insert. Failure expires/cancels the card.
6. Decline starts a 2-hour cooldown for the pair at that venue.
7. Feature flag `ff_calling_cards` gates the HTTP surface in non-test envs when
   disabled.

## Consequences

Calling Card eligibility is stricter than Live Vibe posting. PresenceService
helpers stay separate (`can_post_live_vibe` vs `authorize_calling_card_*`).
