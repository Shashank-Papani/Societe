# ADR 0023: Profile media pipeline reuse

## Status

Accepted

## Context

Live Vibes `media_assets` require venue and check-in. Profile photos need the
same quarantine → process → EXIF strip → moderate path without presence coupling.

## Decision

1. Introduce `app.profile_media_assets` (no venue/check-in FKs).
2. Reuse object storage buckets, processors, and moderation interfaces.
3. Profile photo is optional; onboarding may complete while processing.
4. `users.profile_photo_media_id` updates only after successful processing and
   moderation approval.
5. Until approval: show previous approved photo or placeholder; never quarantine
   or rejected bytes.
6. Single current photo only (no galleries) in Phase 6.

## Consequences

Profile uploads do not require a venue lease. Live Vibe posting authz remains
unchanged aside from onboarding/account gates.
