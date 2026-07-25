# ADR 0019: Refresh session rotation and concurrency

## Status

Accepted

## Context

Mobile clients may fire two refresh requests nearly simultaneously (app resume,
parallel 401 handlers). Treating every reuse of a just-rotated refresh token as
theft would log out legitimate users.

## Decision

1. Store only hashed refresh tokens server-side, bound to a user-owned device.
2. Rotate under `SELECT … FOR UPDATE` on the session row.
3. Keep `previous_token_hash` + `rotated_at` for one generation.
4. On presentation of the previous token within
   `REFRESH_ROTATION_GRACE_SECONDS`, return the cached rotation result from
   Valkey (`auth:refresh_grace:{old_hash}`) — idempotent concurrency, not theft.
5. Outside the grace window, revoke the entire session family.
6. Missing/unknown/expired/revoked tokens return 401 without family side effects
   beyond the matched revoked session.

## Consequences

Concurrent refresh is safe. Genuine replay of an older rotated token still
triggers family revocation. Clients must store refresh tokens in SecureStore.
