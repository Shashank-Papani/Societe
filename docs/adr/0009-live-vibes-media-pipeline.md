# ADR 0009: Phase 3 Live Vibes media pipeline

## Status

Accepted

## Context

Phase 3 lets a user attach a photo or a short video to the venue they are
standing in. That makes the API accept attacker-supplied binaries for the first
time, and it makes a venue's feed a place where a stranger's content is shown to
everyone else in the room. Two failure modes matter more than throughput:
publishing something that was never checked, and leaking who posted an anonymous
vibe.

The upload itself also has to work from a phone on a coffee-shop network, which
rules out proxying bytes through the API and makes the difference between MinIO's
in-cluster hostname and its client-reachable one a functional requirement rather
than a configuration detail.

## Decision

1. **Posting is gated by `can_post_live_vibe`, not `social_features_enabled`.**
   Posting requires an active account, an owned and unrevoked device, and a
   *verified* Valkey lease for the requested venue. `provisional`, `degraded`,
   `refresh_required`, `ambiguous`, `exited`, `revoked`, and `outside` are all
   refused, and an unreachable Valkey refuses too — a durable check-in row is
   never accepted as proof of present-tense location. Ghost Mode,
   `discoverable_in_venue`, and `allow_calling_cards` do **not** block posting;
   Ghost Mode only sets `attribution_mode` to `anonymous`.

2. **One presigned PUT, no multipart.** The largest accepted upload is a 40 MB
   video, which a single PUT handles. Multipart would add per-part accounting,
   abort/cleanup paths, and a second completion protocol for no benefit at this
   size. `ObjectStorage` keeps multipart methods that raise
   `NotImplementedError`, and no multipart route is published, so a client cannot
   discover a half-built flow.

3. **The intent and its draft Live Vibe are created in one transaction.** An
   asset with no post — or a post with no asset — is not representable. The
   presigned URL is minted only after authorization, limits, and declared-value
   checks pass, because a presigned URL is a capability and capabilities are not
   issued for requests that would be rejected.

4. **Completion revalidates everything the intent assumed.** Ownership, device
   ownership, an unexpired and unconsumed intent, a still-verified lease at the
   *same* venue, and an exact byte-size match against the stored object. The
   `media_processing_jobs` row is inserted and the intent marked consumed in the
   same transaction that marks the asset `uploaded`, so an accepted upload can
   never be left with nothing scheduled to look at it. After completion is
   accepted, processing continues even if the author walks out; withdrawing
   consent is a delete, not an exit.

5. **Two buckets, both private: `quarantine` and `processed`.** Original bytes
   land in quarantine and are never served. Only sanitised derivatives are
   uploaded to `processed`, and clients receive short-lived (5 minute) signed
   URLs — object keys never cross the API boundary in either direction.

6. **The server recomputes SHA-256 from the bytes it reads.** An S3 `ETag` is a
   storage implementation detail (multipart, encryption, and provider changes all
   alter it), so it is not an integrity statement. A client-declared checksum is
   compared and logged, never trusted.

7. **Orientation is baked in before metadata is discarded.** Pillow applies the
   EXIF orientation transform first, then every derivative is re-encoded with no
   EXIF block at all. Doing it in the other order silently rotates photos;
   keeping EXIF would ship the GPS tag of the venue's back room. Decoding is
   bounded at 8192 px per edge and 40 MP to keep a decompression bomb from
   becoming a memory incident.

8. **Video is transcoded locally by `ffmpeg` with fixed arguments.** A hard
   timeout, an isolated temporary directory, and no client-supplied arguments of
   any kind. The output is a progressive `video_720` MP4 with `faststart` plus a
   `video_poster` still. No HLS locally: a packaged ladder belongs with a CDN,
   and shipping one now would mean maintaining two playback paths.

9. **Every unclear answer keeps the vibe unpublished.** A scanner that cannot
   run, a moderation provider that raises, an unidentifiable container — all of
   them hold the media rather than passing it. Publication requires an explicit
   approval. The no-op malware scanner and the deterministic fake moderator exist
   for development and tests only; selecting either outside
   `development`/`test` fails startup instead of quietly disabling the check in
   staging.

10. **Moderation reads sanitised derivatives, not the original.** The provider
    receives re-encoded WebP images from a private temporary directory. The raw
    original never leaves quarantine, which limits what a provider integration
    can be handed and keeps EXIF out of third-party systems.

11. **`expires_at` is computed at publication, not at intent.** It is
    `min(next 06:00 in the venue's time zone, published_at + VIBE_ABSOLUTE_MAX_LIFETIME_HOURS)`.
    Computing it at intent would punish slow processing by shortening the window;
    the local-morning boundary matches how a night actually ends, and the
    absolute cap keeps an early-evening post from lingering most of a day.

12. **A retry increments a generation counter rather than overwriting keys.**
    Derivative keys are `processed/{asset_id}/g{generation}/{variant}.{ext}` with
    uniqueness on `(media_asset_id, variant_type, generation)`. A URL a client is
    still holding keeps pointing at bytes that still exist, and a partially
    written retry cannot be mistaken for a complete one.

13. **Status changes go through `MediaLifecycleService` and
    `VibeLifecycleService`.** Routers and workers call these; nothing assigns
    `lifecycle_status` or `publication_status` directly. With thirteen media
    states and nine publication states, an illegal transition written from one
    call site is the likeliest way to publish unmoderated content.

14. **MinIO has two endpoints.** `MINIO_ENDPOINT` is the in-cluster address the
    API and workers use; `MINIO_PUBLIC_ENDPOINT` is what URLs are signed for.
    Signing for `minio:9000` produces a URL that fails on every real device, so
    the two are configured separately and startup rejects a public endpoint that
    resolves to the internal hostname.

15. **Reading a feed requires authentication but not presence.** Someone
    deciding whether to walk into a bar is not standing in it yet. Only
    `published` vibes whose window is open *and* whose media reached `ready` and
    `approved` are returned — a vibe row alone is never sufficient. An anonymous
    vibe carries no author id, handle, or display name; even an opaque id would
    let a viewer correlate several posts back to one person. Pagination uses the
    Phase 1 signed keyset cursor, bound to the venue.

16. **A report is not a takedown button.** `(reporter, vibe)` is unique, reports
    are rate limited, and the auto-hide threshold defaults to disabled. One
    motivated user must not be able to clear a venue's feed; hiding is a
    moderation decision, and every report emits an outbox event for that queue.

17. **Retention is tiered by what each copy is still for.** Incomplete uploads
    are deleted after 24 hours; a processed original is dropped 24 hours after
    its derivatives are serving; a rejected original is kept 3 days as appeal and
    abuse evidence; derivatives survive 7 days past public expiry so a moderator
    can still see what was shown.

18. **Workers claim with `FOR UPDATE SKIP LOCKED` and touch a heartbeat file.**
    Long work never holds a row lock: each phase takes a short transaction to
    advance the state machine, releases it, does the slow part against a private
    temporary directory, then takes another short transaction to record the
    result. The job lease — not the database lock — is what keeps a second worker
    out. Compose health checks read the heartbeat's age, so a worker that is
    alive but wedged is visible.

## Consequences

Publishing is slower than an optimistic write: an upload becomes visible only
after validation, sanitising, and moderation all complete, and any ambiguity
along the way leaves the post unpublished with no user-visible retry. That is the
intended trade.

Local video support depends on `ffmpeg` being present in the API and worker
images, which is why it is installed in the Dockerfile rather than assumed; tests
that need it are skipped when it is missing instead of failing. Because the fake
moderator approves deterministically, no local test run exercises a real
provider's latency or rate limits — the Rekognition path is the first thing to
verify in staging.
