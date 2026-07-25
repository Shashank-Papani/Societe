# Phase 3 implementation plan — Live Vibes and media

Scope: upload intent, single presigned PUT, validation, sanitising processing,
moderation before publication, venue feed, creator history, reports, retention,
media-processor worker, and the mobile Experience tab with a real gallery picker
(`expo-image-picker`) uploading via `expo-file-system` (no Blob/base64). A
bundled JPEG fixture remains as an explicitly labeled `__DEV__`-only path.
No multipart, no AppSync/push, no Calling Cards, no Terraform apply.

## 1. Contracts

```text
POST   /v1/media/uploads                  intent + draft vibe + one presigned PUT
POST   /v1/media/uploads/{id}/complete    revalidate, mark uploaded, enqueue job
GET    /v1/media/uploads/{id}             uploader-only status
GET    /v1/venues/{venue_id}/vibes        published feed, signed keyset cursor
DELETE /v1/vibes/{vibe_id}                author delete
POST   /v1/vibes/{vibe_id}/reports        one report per reporter per vibe
```

Multipart part endpoints are deliberately absent. `ObjectStorage` keeps
multipart methods as `NotImplementedError` stubs so a future phase has a seam
without a half-built resumable path today.

## 2. Posting authorization

`PresenceService.can_post_live_vibe(user, venue_id, device)` is the single
authority. It reads the Valkey lease, never a durable `check_ins` row:

| Condition | Result |
| --- | --- |
| account not active / deleted | reject |
| device not owned / revoked | reject |
| Valkey unavailable | reject (fail closed) |
| no lease | reject `presence_refresh_required` |
| lease state `provisional`, `degraded`, `exited` | reject |
| `verified_until` in the past | reject `presence_refresh_required` |
| lease venue ≠ requested venue | reject `presence_venue_mismatch` |
| verified, same venue, live lease | allow |

`social_features_enabled` is **not** consulted. Ghost Mode, `discoverable`, and
`allow_calling_cards` never block posting; Ghost Mode only sets
`attribution_mode = anonymous` on the snapshot taken at intent time.

## 3. Upload flow

1. `POST /v1/media/uploads` — validate flag, declared MIME/size/duration,
   caption, tags, rate limits, then authorize. One transaction creates the
   `media_assets` row (`intent_pending`) and the `live_vibes` row (`draft`).
   Response carries a single presigned PUT against the **public** endpoint.
2. Client PUTs the bytes to the quarantine bucket.
3. `POST /v1/media/uploads/{id}/complete` — revalidate ownership, device, intent
   not expired or consumed, presence still `verified`, venue unchanged from the
   snapshot. `HEAD` the object and require an exact `declared_byte_size` match.
   One transaction marks `uploaded`, stamps `intent_consumed_at`, and inserts the
   `validate_process` job.
4. Abandoned intents expire the asset (`upload_expired`) and its draft vibe.

Once completion is accepted, processing continues even if the user leaves the
venue. Presence gates the decision to accept, not the pipeline.

## 4. State machines

`MediaLifecycleService` and `VibeLifecycleService` own every status write.
Routers and workers call them; nobody assigns `lifecycle_status` or
`publication_status` directly. Illegal transitions raise a 409.

`expires_at` is computed at **publication** time:
`min(next 06:00 in the venue's time zone, published_at + VIBE_ABSOLUTE_MAX_LIFETIME_HOURS)`.

## 5. Processing

* Images (Pillow): sniff by signature, guard 8192 px per side and 40 MP decoded,
  normalise orientation **then** strip EXIF/GPS by re-encoding pixels into a
  fresh image, emit `image_1080`, `image_720`, `thumbnail` as WebP.
* Video (local `ffmpeg`): fixed argument vector, isolated temp dir, hard timeout,
  no client-supplied arguments. Emits a progressive `video_720` MP4 and a
  `video_poster`. No HLS locally.
* SHA-256 is computed by the server from the downloaded bytes. ETag is never
  trusted as a checksum.
* Malware scan runs before any derivative is produced. `NoOpMalwareScanner` is
  dev/test only; configuring it elsewhere fails startup, and an unimplemented
  provider fails closed to quarantine.
* Moderation reads sanitised derivatives, never the raw original.
* Derivatives live in `app.media_derivatives`, unique on
  `(media_asset_id, variant_type, generation)`, keyed
  `processed/{asset_id}/g{generation}/image_1080.webp`.

## 6. Feed

Auth required, presence not required. Only `published` and not yet expired.
Order `published_at DESC, id DESC` with an HMAC-signed keyset cursor bound to a
query fingerprint, matching Phase 1. Anonymous vibes carry no author id, handle,
or display name. Object keys never leave the server; clients get signed URLs
with a 5 minute TTL.

## 7. Worker

`services/workers/media_processor` claims jobs with `FOR UPDATE SKIP LOCKED`,
handles `validate_process` and `moderate` in one binary, and runs the expiry and
retention cycles. It writes a heartbeat file so the Compose healthcheck fails
when a cycle wedges.

Retention: incomplete uploads 24 h, processed originals quarantined 24 h,
rejected originals 3 d, processed derivatives 7 d after public expiry.

## 8. Storage endpoints

`MINIO_ENDPOINT` is the in-cluster URL the API and worker use. Presigned URLs
handed to a client are always generated against `MINIO_PUBLIC_ENDPOINT`
(localhost, `10.0.2.2`, or a LAN address). Startup refuses a public endpoint that
points at the internal Compose hostname.

## 9. Verification

`make migrate`, `make seed`, `ruff check`, `ruff format --check`, `mypy`,
`pytest`, `make openapi`. Tests enable `FF_MEDIA_POSTING` through `conftest`.
