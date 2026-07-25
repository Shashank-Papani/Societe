# ADR 0018: Passwordless email OTP and email provider abstraction

## Status

Accepted

## Context

Architecture §18.1 centers Cognito with optional OTP. Product Phase 6 requires
custom passwordless email OTP now, without Cognito migration or social login.
Mailpit exists locally; production must use a provider abstraction (AWS SES)
without deploying infrastructure in this phase.

## Decision

1. Implement custom email OTP that mints Societe JWTs when `AUTH_PROVIDER=local`.
2. Cognito adapter remains unused; social login stays out of scope.
3. `EmailSender` protocol with:
   - `SmtpMailpitSender` — development/test only
   - `SesEmailSender` — staging/production configuration path (no hardcoded creds)
4. Startup and OTP request **fail closed** when the configured provider is missing
   or invalid for the environment. Never fall back to Mailpit, console OTP,
   returned codes, or no-op senders outside development/test.
5. OTP codes are CSPRNG, short-lived, one-time, hashed at rest, rate-limited per
   email and IP, with generic responses (no account enumeration).
6. `POST /v1/auth/local/token` (Dev Alpha/Beta) remains gated to
   `APP_ENV ∈ {development, test}`.

## Consequences

Normal users authenticate via OTP. Dev personas continue for dual-simulator DX.
Staging/production require a real email provider configuration before OTP works.
