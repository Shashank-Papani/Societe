# Société — current state

Last updated: 2026-07-25 (Phase 6 auth / onboarding / profiles in progress)

## Completed phases

| Phase | Status | Tag / notes |
|-------|--------|-------------|
| 0 Foundation | Complete | `phase-0-complete` |
| 1 Identity + venues | Complete | `phase-1-complete` |
| 2 Presence + geofencing | Complete | `phase-2-complete` |
| 3 Live Vibes + media | Complete | Checkpoint commit; gallery upload verified |
| 4 Calling Cards + realtime | Complete | `phase-4-complete` |
| 5 Private messaging | Complete | Merged to main |
| 6 Auth / onboarding / profiles | In progress | Product Phase 6 (architecture Phase 1 gaps) |

## Latest migration

`0007_auth_onboarding_profiles` — OTP identities/challenges, refresh sessions,
policy acceptance history, onboarding/age fields, profile media, privacy
extensions.

Previous: `0006_private_messaging`.

## Feature flags (local)

```text
FF_CALLING_CARDS=true
FF_VENUE_PEOPLE_DISCOVERY=true
FF_PRIVATE_MESSAGING=true
FF_LOCATION_SIMULATOR=true
FF_MEDIA_POSTING=true
EMAIL_PROVIDER=mailpit
```

Do not commit `.env` or production secrets.

## Auth notes

- Normal users: passwordless email OTP (`/v1/auth/otp/*`) + rotating refresh.
- Dev Alpha / Dev Beta: `POST /v1/auth/local/token` only when
  `APP_ENV` is development/test.
- Access token TTL remains configurable (default 60) until mobile refresh +
  single-retry-on-401 are verified; 15 minutes is the approved next default.
- Staging/production require `EMAIL_PROVIDER=ses` (fail closed; no Mailpit fallback).

## Manual tests (Phase 6)

1. New email → OTP via Mailpit → onboarding → main app.
2. Restart app → session restores (refresh if needed).
3. Sign out → OTP sign-in restores same account.
4. Second session → revoke → refresh fails.
5. Privacy changes affect discovery/cards/messaging.
6. Deactivate → social actions stop; OTP offers reactivation.
7. Dev Alpha / Dev Beta still work at Echo Basement (vibes, cards, messages).

## Known limitations

- Cognito / Apple / Google sign-in deferred.
- Production SES not deployed in this phase.
- Profile photo is single optional asset (no gallery).
- Username locked after onboarding (Phase 6).
- No regulatory compliance claims without legal review.

## Next recommended phase

Architecture Safety / anti-spoofing, or production infrastructure, per product
priority.
