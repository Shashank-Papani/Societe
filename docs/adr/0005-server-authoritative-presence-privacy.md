# ADR 0005 — Server-authoritative presence and privacy

## Status

Accepted

## Context

Client-claimed venue membership is spoofable. Exact coordinates and small-crowd
counts create stalking and re-identification risk.

## Decision

The backend alone authorizes venue presence, Calling Card eligibility, blocks,
Ghost Mode, and media publication. Precise coordinates are never exposed to
other users. Sensitive actions fail closed on stale or ambiguous presence.

## Consequences

Mobile UX must refresh presence before social actions. Ambiguous overlapping
venues require explicit verification rather than silent selection.
