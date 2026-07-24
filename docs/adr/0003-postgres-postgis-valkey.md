# ADR 0003 — PostgreSQL/PostGIS + Valkey ownership

## Status

Accepted

## Context

Presence authorization must be server-authoritative and spatial. High-frequency
heartbeats must not become durable GPS streams.

## Decision

Aurora PostgreSQL + PostGIS is the durable source of truth. Valkey holds
short-lived presence leases, rate limits, and rebuildable caches. Local
development uses PostGIS 16 and Valkey 8 via Compose.

## Consequences

Calling Cards and sensitive actions fail closed when leases are missing or
Valkey is unavailable. Raw location retention is minimized and purged.
