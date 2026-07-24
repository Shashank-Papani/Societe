# ADR 0006 — Monorepo tooling (pnpm + uv)

## Status

Accepted

## Context

Société spans mobile, API, workers, contracts, and Terraform. Tooling must keep
Python and JavaScript dependency graphs coherent in one repository.

## Decision

Use a pnpm workspace for JS/TS packages and a root uv workspace for Python
(`services/api` member) with a root `uv.lock`. Pin Node 24 LTS via `.nvmrc`.
Pin Compose image tags explicitly (no `:latest`).

## Consequences

`make bootstrap` installs both ecosystems. CI uses Node 24 and uv sync from the
root lockfile.
