# Société — current state

Last updated: 2026-07-24 (Phase 5 private messaging in progress / implemented locally)

## Completed phases

| Phase | Status | Tag / notes |
|-------|--------|-------------|
| 0 Foundation | Complete | `phase-0-complete` |
| 1 Identity + venues | Complete | `phase-1-complete` |
| 2 Presence + geofencing | Complete | `phase-2-complete` |
| 3 Live Vibes + media | Complete | Checkpoint commit; gallery upload verified |
| 4 Calling Cards + realtime | Complete | `phase-4-complete` |
| 5 Private messaging | Implemented locally | Not committed/tagged yet |

## Latest migration

`0006_private_messaging` — conversations, conversation_members, messages;
`connection_grants.expires_at` nullable (NULL = durable for messaging).

## Feature flags (local)

```text
FF_CALLING_CARDS=true
FF_VENUE_PEOPLE_DISCOVERY=true
FF_PRIVATE_MESSAGING=true
FF_LOCATION_SIMULATOR=true
FF_MEDIA_POSTING=true
```

Do not commit `.env` or production secrets.

## Manual tests (Phase 5)

1. Accept a Calling Card between Dev Alpha / Dev Beta.
2. Open Messages from Connect; create/open conversation.
3. Send both directions without manual refresh (realtime invalidation).
4. Unread clears on open.
5. Offline send → reconnect → exactly one copy.
6. Leave venue → messaging still works (durable grant).
7. Block → new sends rejected; history intact; unblock restores grant + messaging.

## Known limitations

- Text-only messages (no media / reactions / typing / E2E).
- Architecture §25 “Phase 5 Safety” (App Attest, QR, BLE) is deferred; product
  Phase 5 is private messaging (see ADRs 0014–0017).
- Push is local stub only.

## Next recommended phase

Safety and anti-spoofing (architecture’s former Phase 5), or production infra,
per product priority.
