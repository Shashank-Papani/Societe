# ADR 0007: Phase 1 map cache and identity boundaries

## Status

Accepted

## Context

Phase 1 needs nearby venue discovery with Valkey acceleration and Cognito-compatible
identity, without presence enforcement or H3-driven query narrowing.

## Decision

1. Nearby results always come from an authoritative PostGIS `ST_DWithin` query.
   `venue:static:v1:{venue_id}` hydrates static card fields only and never decides
   membership. H3 / `map:cell:v1:*` is deferred; no H3 dependency in Phase 1.
2. Public `/me` and venue responses omit auth subjects and security geometry /
   proof capability fields.
3. Idempotency uses Valkey `SET NX` with `processing` / `completed` / `failed`
   states. POSTs require `Idempotency-Key`; PATCH/DELETE support it optionally.
4. Device `(platform, installation_id)` is unique; ownership never silently
   transfers across active accounts.
5. Mobile Discover uses `MapProvider` + `DevelopmentMapProvider` only.

## Consequences

Cache misses cannot hide venues. Concurrent identical idempotent writes return
`IDEMPOTENCY_REQUEST_IN_PROGRESS` instead of double-applying. Mapbox and H3 can
be added later without changing PostGIS correctness.
