# ADR 0021: Age eligibility and date-of-birth privacy

## Status

Accepted

## Context

Calling Cards already consult `age_verified` for venue minimum age. Product
Phase 6 requires server-derived eligibility from date of birth, with a global
minimum separate from venue 21+ rules.

## Decision

1. Store `date_of_birth` as `DATE` on `app.users`.
2. Compute age as completed years using the **UTC calendar date** of the request.
3. Global minimum age is configurable (`MINIMUM_AGE_YEARS`, default 18).
4. Under global minimum → `onboarding_state=age_ineligible`, `age_verified=false`.
5. Eligible → derive `age_band` server-side and set `age_verified=true`.
6. Clients cannot set `age_verified` or `age_band` via profile PATCH.
7. Full DOB is returned only on owner `/v1/me`; never on discovery/public cards.
8. Venue `minimum_age` (e.g. 21+) remains a separate Calling Card check.

## Consequences

Underage users are not stuck in `age_required`. Social features stay denied until
eligible and onboarding completes.
