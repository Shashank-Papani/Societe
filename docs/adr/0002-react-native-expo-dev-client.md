# ADR 0002 — React Native + Expo custom development client

## Status

Accepted

## Context

We need cross-platform delivery speed plus access to advanced Core Location,
Play Integrity, and future native presence proofs.

## Decision

Use React Native with Expo SDK (custom development client + prebuild), Expo
Router, TanStack Query, Zustand, and SecureStore. Do not depend on Expo Go for
production-like builds.

## Consequences

Native modules can be added under `apps/mobile/modules/` without abandoning the
Expo workflow. Mapbox and presence-proof natives are deferred past Phase 0.
