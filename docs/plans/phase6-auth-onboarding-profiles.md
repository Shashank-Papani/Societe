# Phase 6 implementation plan — Auth, onboarding, profiles

Product Phase 6 replaces development-identity dependence for normal users with
passwordless email OTP, server-authoritative onboarding, profiles, privacy,
device/session management, and account lifecycle.

Architecture §25 numbers this work under Phase 1 (identity). Product Phase 6
overrides numbering only. Cognito migration, social login, and production SES
deployment remain out of scope.

## Corrections from approval

1. **Policy acceptance history** in `app.user_policy_acceptances` (durable;
   unique `(user_id, policy_type, policy_version)`). Users may cache completion
   flags only.
2. **Concurrent-safe refresh rotation** with row locks + short grace/idempotency
   replay via Valkey. Family revoke only for replay outside the grace case.
3. **`age_ineligible` onboarding state** for underage accounts (explain / sign
   out / delete only; no social).
4. **Explicit privacy choices** for new OTP users; conservative DB defaults;
   onboarding privacy step requires explicit choices.
5. **Transactional OTP verify** binds device ownership before refresh session.
6. **Profile photo optional**; onboarding completes while media processes;
   public pointer swaps only after moderation approval.
7. **Username locked after onboarding** (no unrestricted PATCH rename).
8. **Reactivation via OTP** on deactivated accounts; never auto-reactivate
   `deletion_requested`.
9. **Atomic OTP verification** (no duplicate users/identities/devices/sessions).
10. **Email provider fail-closed** outside development/test (no Mailpit/no-op
    fallback).
11. **Access token TTL** stays at current configurable default until mobile
    refresh + single-retry-on-401 are implemented and tested; then 15 minutes
    may be adopted.
12. **Scope** — no Cognito, social login, SES deploy, anonymous venues, redesign,
    multi-photo galleries.

## Build order

1. ADRs + this plan + `.env.example`
2. Migration `0007_auth_onboarding_profiles`
3. Email / OTP / refresh sessions / auth routes
4. Onboarding, profile, privacy, devices, blocks, lifecycle APIs
5. Social/messaging/media authz gates
6. Profile-media upload path
7. Mobile auth, onboarding, settings
8. Tests + OpenAPI + quality gates

## Quality gates

Backend fmt/lint/mypy; migrate from `0006` and empty DB; full pytest; OpenAPI
check; mobile typecheck/lint/tests; Compose build; secret scan; `git diff --check`.

Do not commit, tag, push, deploy, or apply Terraform.
