# ADR 0001 — Modular monolith on AWS

## Status

Accepted

## Context

Société needs high concurrency around weekends, PostGIS presence checks, and
clear service boundaries without premature distributed complexity.

## Decision

Ship a modular FastAPI monolith on ECS Fargate with independently scalable
workers. Preserve package boundaries so modules can split later. Use AWS as the
sole cloud for the first production system.

## Consequences

Faster MVP delivery and simpler ops. Service extraction is deferred until
scaling or failure-domain triggers from the architecture document are met.
