# ADR 0012: Realtime provider abstraction

## Status

Accepted

## Context

Production will use AWS AppSync Events. Local development cannot depend on AWS
credentials or `terraform apply`. ADR 0004 already requires REST for mutations.

## Decision

1. Define `RealtimePublisher` with `publish(channel, event_id, event_type, payload)`.
2. Local adapter: in-process / Compose WebSocket hub with authenticated
   user-scoped channels (`user:{user_id}`), reconnect, and event-id dedupe on
   the client.
3. AppSync adapter: interface + config + Terraform module stub only. No apply,
   no production secrets in the repo.
4. Clients never treat a realtime payload as durable state; they refetch via REST
   using the event's aggregate id.

## Consequences

Dispatcher code is provider-agnostic. Local integration tests exercise the WS
adapter; AppSync remains a Phase-6+ wiring concern.
