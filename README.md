# Société

Real-time nightlife discovery and in-venue social connection.

This repository is the Societe monorepo. The authoritative architecture lives in
[`docs/societe_cursor_master_architecture.md`](docs/societe_cursor_master_architecture.md).

## Phase 4 status (Calling Cards + realtime)

- Same-venue Calling Cards, discovery, blocks, outbox dispatcher
- Local realtime: API hosts `WS /v1/realtime/ws` (Bearer) + Valkey fan-out
- `POST /v1/events/{event_id}/ack` and push fallback when ack is missing
- AppSync Events adapter + Terraform stub only (no apply)

Not included: production AppSync/APNs/FCM, QR/BLE/Wi-Fi proofs, App Attest /
Play Integrity, AWS deploy.

## Quick start

```bash
fnm use 24
make bootstrap
make dev-up
make migrate
make seed
make test
```

Mobile:

```bash
cd apps/mobile && pnpm start
```
