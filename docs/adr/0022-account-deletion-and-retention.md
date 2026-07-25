# ADR 0022: Account deactivation, deletion, and retention

## Status

Accepted

## Context

Phase 1 soft-deletion exists (`deletion_requested` + device revoke). Phase 6 adds
deactivation and must define reactivation after session revocation.

## Decision

1. **Deactivate** sets `account_status=deactivated`, `deactivated_at`, revokes all
   refresh sessions and devices, removes discovery eligibility, blocks new cards
   and messages.
2. **Reactivate** only via OTP verify on a deactivated account:
   - response indicates `reactivation_required`
   - explicit `POST /v1/me/account-reactivation` (or verify flag) restores
     `active` on the **same** user row
   - never create a duplicate identity/user
3. **`deletion_requested` / `deleted`** never auto-reactivate.
4. Deletion remains soft/tombstone: revoke sessions, scrub live discoverability,
   retain messages/reports/audit as needed for integrity and safety.
5. Policy acceptances remain in `user_policy_acceptances`.
6. No regulatory compliance claims without legal review.

## Consequences

Deactivated users sign in with OTP, confirm reactivation, then resume. Deleted
accounts stay non-social and non-login (except deletion idempotency paths).
