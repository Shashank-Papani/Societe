# Société

Real-time nightlife discovery and in-venue social connection.

This repository is the Societe monorepo. The authoritative architecture lives in
[`docs/societe_cursor_master_architecture.md`](docs/societe_cursor_master_architecture.md).

## Phase 2 status

Server-authoritative presence and geofencing:

- Location evidence API with PostGIS boundary candidates + `ST_Covers`
- Check-in state machine with verified → degraded → exited leases
- Valkey presence leases + discoverable membership (Ghost Mode aware)
- Lease expiry worker (`location-aggregator`) and evidence purge
- Development location simulator (flag-gated)
- Mobile auth sync fix + Presence tab (Expo Location foreground)

Not included: Calling Cards, Live Vibes, media, AppSync, push, QR/BLE/Wi-Fi
proofs, App Attest / Play Integrity, AWS deploy.

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
