import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  officialPostListSchema,
  storyGroupListSchema,
  storyGroupSummarySchema,
  storySlideSchema,
  storyUploadResponseSchema,
} from "./storySchemas.ts";
import {
  applyOptimisticView,
  isSafeExternalCtaUrl,
  shouldRecordView,
  storyGroupAccessibilityLabel,
} from "./storyHelpers.ts";

const uuid = "11111111-1111-4111-8111-111111111111";
const venueId = "22222222-2222-4222-8222-222222222222";

const variant = {
  variant_type: "story",
  mime_type: "image/jpeg",
  url: "https://cdn.example/story.jpg?sig=1",
  width: 1080,
  height: 1920,
  duration_ms: null,
  expires_at: "2026-07-30T00:00:00Z",
};

describe("Story contract schemas", () => {
  it("parses a Story group summary", () => {
    const group = storyGroupSummarySchema.parse({
      group_key: "user:abc",
      group_type: "user",
      venue_id: venueId,
      author: { id: uuid, handle: "alpha", display_name: "Alpha" },
      author_label: "Alpha",
      venue: { id: venueId, name: "Noir", slug: "noir" },
      is_official: false,
      is_mine: false,
      preview_variants: [variant],
      active_count: 2,
      unviewed_count: 1,
      latest_published_at: "2026-07-29T20:00:00Z",
      earliest_expires_at: "2026-07-30T20:00:00Z",
    });
    assert.equal(group.group_key, "user:abc");
    assert.equal(group.unviewed_count, 1);
  });

  it("parses a Story slide", () => {
    const slide = storySlideSchema.parse({
      story_id: uuid,
      venue_id: venueId,
      media_type: "image",
      attribution_mode: "attributed",
      author: { id: uuid, handle: "alpha", display_name: "Alpha" },
      author_label: "Alpha",
      venue: { id: venueId, name: "Noir", slug: "noir" },
      caption: "Night",
      vibe_tags: ["live"],
      reply_policy: "disabled",
      published_at: "2026-07-29T20:00:00Z",
      expires_at: "2026-07-30T20:00:00Z",
      viewed: false,
      is_mine: false,
      can_report: true,
      can_delete: false,
      variants: [variant],
    });
    assert.equal(slide.story_id, uuid);
    assert.equal(slide.can_report, true);
  });

  it("rejects anonymous projections that include author identity", () => {
    assert.throws(() =>
      storyGroupSummarySchema.parse({
        group_key: "anon:xyz",
        group_type: "anon",
        author: { id: uuid, handle: "secret", display_name: "Secret" },
        author_label: "Someone nearby",
        is_official: false,
        active_count: 1,
        unviewed_count: 1,
        latest_published_at: "2026-07-29T20:00:00Z",
        earliest_expires_at: "2026-07-30T20:00:00Z",
      }),
    );
  });

  it("parses official groups without staff author", () => {
    const group = storyGroupSummarySchema.parse({
      group_key: "venue:abc",
      group_type: "venue",
      venue_id: venueId,
      author: null,
      author_label: "Noir",
      venue: { id: venueId, name: "Noir", slug: "noir" },
      is_official: true,
      active_count: 1,
      unviewed_count: 0,
      latest_published_at: "2026-07-29T20:00:00Z",
      earliest_expires_at: "2026-07-30T20:00:00Z",
    });
    assert.equal(group.is_official, true);
    assert.equal(group.author, null);
  });

  it("rejects official slides with staff author projection", () => {
    assert.throws(() =>
      storySlideSchema.parse({
        story_id: uuid,
        venue_id: venueId,
        media_type: "image",
        attribution_mode: "official",
        author: { id: uuid, handle: "staff", display_name: "Staff" },
        author_label: "Noir",
        is_official: true,
        vibe_tags: [],
        reply_policy: "disabled",
        published_at: "2026-07-29T20:00:00Z",
        expires_at: "2026-07-30T20:00:00Z",
        variants: [],
      }),
    );
  });

  it("rejects malformed public responses", () => {
    assert.throws(() =>
      storyGroupListSchema.parse({
        items: [{ group_key: "x" }],
      }),
    );
  });

  it("rejects upload responses that expose object keys", () => {
    assert.throws(() =>
      storyUploadResponseSchema.parse({
        story_id: uuid,
        upload_id: uuid,
        media_asset_id: uuid,
        lifecycle_status: "intent_pending",
        publication_status: "draft",
        moderation_status: "pending",
        attribution_mode: "attributed",
        intent_expires_at: "2026-07-29T21:00:00Z",
        max_byte_size: 12_000_000,
        upload: {
          method: "PUT",
          url: "https://minio.example/put",
          headers: { "Content-Type": "image/jpeg" },
          expires_at: "2026-07-29T21:00:00Z",
        },
        object_key: "stories/abc",
      }),
    );
  });

  it("parses official-post pagination", () => {
    const page = officialPostListSchema.parse({
      items: [
        {
          post_id: uuid,
          venue_id: venueId,
          post_type: "announcement",
          title: "Tonight",
          body: "Doors at 10",
          call_to_action_type: "tickets",
          call_to_action_url: "https://example.com/tickets",
          publication_status: "published",
          published_at: "2026-07-29T18:00:00Z",
          is_official: true,
          author_label: "Noir",
          venue: { id: venueId, name: "Noir", slug: "noir" },
          variants: [],
        },
      ],
      next_cursor: "cursor-2",
    });
    assert.equal(page.items.length, 1);
    assert.equal(page.next_cursor, "cursor-2");
  });

  it("rejects official posts that include staff identity fields", () => {
    assert.throws(() =>
      officialPostListSchema.parse({
        items: [
          {
            post_id: uuid,
            venue_id: venueId,
            post_type: "general",
            body: "Hi",
            publication_status: "published",
            author_label: "Noir",
            created_by_user_id: uuid,
            variants: [],
          },
        ],
      }),
    );
  });
});

describe("Story helpers", () => {
  it("exposes viewed/unviewed without relying on color alone", () => {
    const label = storyGroupAccessibilityLabel({
      group_key: "g1",
      group_type: "user",
      author_label: "Alpha",
      is_official: false,
      is_mine: false,
      preview_variants: [],
      active_count: 3,
      unviewed_count: 2,
      latest_published_at: "2026-07-29T20:00:00Z",
      earliest_expires_at: "2026-07-30T20:00:00Z",
    });
    assert.match(label, /unviewed/i);
    assert.match(label, /Alpha/);
  });

  it("preserves backend ordering while applying optimistic views", () => {
    const groups = [
      {
        group_key: "a",
        group_type: "user" as const,
        author_label: "A",
        is_official: false,
        is_mine: false,
        preview_variants: [],
        active_count: 1,
        unviewed_count: 1,
        latest_published_at: "2026-07-29T20:00:00Z",
        earliest_expires_at: "2026-07-30T20:00:00Z",
      },
      {
        group_key: "b",
        group_type: "anon" as const,
        author_label: "Someone nearby",
        is_official: false,
        is_mine: false,
        preview_variants: [],
        active_count: 1,
        unviewed_count: 0,
        latest_published_at: "2026-07-29T19:00:00Z",
        earliest_expires_at: "2026-07-30T19:00:00Z",
      },
    ];
    const next = applyOptimisticView(groups, uuid, "a");
    assert.equal(next[0]?.group_key, "a");
    assert.equal(next[0]?.unviewed_count, 0);
    assert.equal(next[1]?.group_key, "b");
  });

  it("records views only after genuine display threshold", () => {
    assert.equal(
      shouldRecordView({ visibleMs: 400, mediaType: "image", alreadyRecorded: false }),
      false,
    );
    assert.equal(
      shouldRecordView({ visibleMs: 1000, mediaType: "image", alreadyRecorded: false }),
      true,
    );
    assert.equal(
      shouldRecordView({ visibleMs: 5000, mediaType: "image", alreadyRecorded: true }),
      false,
    );
  });

  it("allows only https CTA schemes", () => {
    assert.equal(isSafeExternalCtaUrl("https://example.com/x"), true);
    assert.equal(isSafeExternalCtaUrl("http://example.com/x"), false);
    assert.equal(isSafeExternalCtaUrl("javascript:alert(1)"), false);
    assert.equal(isSafeExternalCtaUrl(null), false);
  });
});
