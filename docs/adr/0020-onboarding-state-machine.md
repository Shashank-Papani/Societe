# ADR 0020: Server-authoritative onboarding state machine

## Status

Accepted

## Context

Clients must not decide whether a user may use social features. Incomplete
onboarding should still allow public venue browsing while authenticated.

## Decision

States:

- `authentication_verified`
- `profile_required`
- `age_required`
- `age_ineligible`
- `policy_acceptance_required`
- `privacy_required`
- `completed`

Rules:

1. Server transitions only via dedicated onboarding endpoints.
2. Username is chosen during onboarding and **locked afterward** in Phase 6.
3. Privacy step requires explicit choices; new OTP users start with conservative
   defaults (all discoverability/messaging off).
4. `age_ineligible` users may view explanation, sign out, request deletion, and
   see support/legal info — not discovery, Calling Cards, Live Vibes, or messaging.
5. Profile photo is optional and does not block `completed`.
6. Dev Alpha/Beta provision directly to `completed` with age eligibility.

Incomplete (non-`age_ineligible`) users may use venue catalog APIs; social
modules deny with stable error codes.

## Consequences

Onboarding resumes after restart from `/v1/me`. Social authz checks onboarding
completion (and rejects `age_ineligible`).
