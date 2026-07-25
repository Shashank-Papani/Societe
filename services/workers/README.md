# Workers

Each worker imports the API's service layer directly rather than calling the API
over HTTP, so a state transition cannot drift between the request path and the
background path. All of them claim work with `FOR UPDATE SKIP LOCKED` and refresh
a heartbeat file that the Compose healthcheck reads, because a process that is
"up" while its loop is wedged should not report healthy.

| Package | Status | Runs |
|---------|--------|------|
| `location_aggregator` | Phase 2 | Presence lease transitions and location-evidence purge |
| `media_processor` | Phase 3 | `validate_process` and `moderate` jobs, Live Vibe expiry, media retention |
| `event_dispatcher` | Phase 4 | Outbox → local realtime (API WS + Valkey) + ack-gated push fallback |
| `moderation` | Folded into `media_processor` | — |

`moderation` is deliberately not a separate deployment: validation and moderation
need the same ffmpeg/Pillow image and the same object storage credentials, and one
binary keeps a single place where the pipeline's ordering is expressed. If a
provider integration later needs its own scaling profile, `media_processor` already
selects jobs by `job_type`, so splitting it is a deployment change rather than a
rewrite.

Run one locally:

```bash
docker compose up media-processor
```
