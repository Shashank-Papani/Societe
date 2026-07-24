# ADR 0008: Phase 2 presence evidence, leases, and expiry

## Status

Accepted

## Context

Phase 2 turns location evidence into a server-authoritative presence state that
later phases use to authorize Calling Cards. The evidence is fused GPS only:
Wi-Fi, BLE, QR, and device attestation are Phase 5 work. That makes it easy to
build something that looks correct in a test venue and is wrong in a dense
nightlife block, where polygons touch, GPS accuracy is poor indoors, and clients
control their own clocks.

## Decision

1. **Server time is authoritative.** `observed_at` is validated for freshness
   (`MAX_EVIDENCE_AGE_SECONDS`) and forward skew
   (`MAX_OBSERVED_FUTURE_SKEW_SECONDS`) and is then discarded for decision
   purposes. Dwell windows, lease deadlines, and evidence `purge_at` all derive
   from the server's `received_at`.

2. **Candidates come from the boundary, not the centroid.**
   `ST_DWithin(v.boundary::geography, sample.geog, :radius_m)` with
   `ST_Covers` for containment. A large irregular venue can cover a point that
   sits hundreds of metres from its centroid; a centroid prefilter silently
   loses it. `harbor-yards-campus` in the local seed exists to keep this
   regression visible.

3. **Ambiguity fails closed.** Two polygons covering the point, a neighbour
   within the reported accuracy radius, or a shared boundary all produce
   `ambiguous`. No verified lease is issued, and an existing check-in is
   degraded in place rather than reassigned. Guessing between adjacent venues
   would put a stranger in the wrong room.

4. **Verified is strictly gated.** `ST_Covers` **and** accuracy within
   `venue.max_gps_accuracy_m` **and** entry dwell satisfied **and** unambiguous.
   Inside the entry buffer but outside the polygon is `provisional` only, which
   never enables social features. `verification_level` is `weak` or `standard`;
   `strong` is reserved for QR/BLE proofs that do not exist yet.

5. **Exit needs corroboration.** A sample is credible-outside only when
   `boundary_distance_m - accuracy_m > exit_buffer_m`, and exit requires two
   such samples separated by `exit_dwell_seconds` of server time. One bad fix
   never ejects a user.

6. **PostgreSQL commits before Valkey.** The check-in row and its outbox event
   commit first; the lease is written second. If Valkey fails, the durable
   record stands, `social_features_enabled` is `false`, and an operational error
   is logged. Presence authorization is never inferred from an old check-in row.

7. **A cache miss is `refresh_required`, not `outside`.** `GET /presence/me`
   with a durable active check-in but no lease asks the client to re-prove.
   Reporting `outside` would look like a location change that never happened.

8. **Raw location is not durable by default.** `ephemeral.location_evidence` is
   written only on state transitions, ambiguity, mock/simulated signals, or
   elevated risk. `purge_at` is the next 06:00 in the venue's time zone (or
   `DEFAULT_PURGE_TIMEZONE` when no venue resolved), capped by
   `EVIDENCE_ABSOLUTE_MAX_RETENTION_HOURS`. The dwell buffer in Valkey stores
   verdicts only — never coordinates.

9. **Expiry is a worker, not a cron.** `location_aggregator` imports
   `PresenceService` directly and runs `FOR UPDATE SKIP LOCKED` batches every
   30 seconds for lease transitions and every 15 minutes for evidence purge.
   Venues span time zones, so a single global 06:00 job is wrong.

10. **The simulator is a build-time capability, not a runtime toggle.**
    `POST /v1/dev/location/simulate` requires both `APP_ENV` in
    `development`/`test` and `FF_LOCATION_SIMULATOR`. Setting the flag under
    staging or production fails startup. It replays the production engine with
    `is_simulated=true` rather than shipping a second decision path.

## Consequences

Adjacent-venue ambiguity and poor indoor accuracy produce `provisional` or
`ambiguous` far more often than `verified`, which is the intended trade: the
Phase 5 QR/BLE proofs are what will raise the verified rate, not a looser
geofence. Evidence schemas reject unknown fields, so a client that starts
sending proof envelopes fails loudly instead of having them ignored while the
response still reads `verified`.
