import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  LIVE_VIBE_MEDIA_ASPECT_RATIO,
  reconcileVibeFeed,
  resolveVibeMediaSource,
} from "./vibeMedia.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.join(here, "../../..");

function read(rel: string) {
  return readFileSync(path.join(mobileRoot, rel), "utf8");
}

describe("resolveVibeMediaSource", () => {
  it("prefers approved remote media over local optimistic URI", () => {
    const resolved = resolveVibeMediaSource({
      variants: [
        {
          variant_type: "thumbnail",
          mime_type: "image/jpeg",
          url: "https://cdn.example/thumb.jpg",
          expires_at: "2099-01-01T00:00:00Z",
        },
        {
          variant_type: "image_1080",
          mime_type: "image/webp",
          url: "https://cdn.example/feed.webp",
          expires_at: "2099-01-01T00:00:00Z",
        },
      ],
      localUri: "file:///tmp/local.jpg",
      pending: true,
    });
    assert.deepEqual(resolved, {
      kind: "remote",
      uri: "https://cdn.example/feed.webp",
      variantType: "image_1080",
    });
  });

  it("uses local URI only while pending and remote is missing", () => {
    const pending = resolveVibeMediaSource({
      variants: [],
      localUri: "file:///tmp/local.jpg",
      pending: true,
    });
    assert.deepEqual(pending, { kind: "local", uri: "file:///tmp/local.jpg" });

    const done = resolveVibeMediaSource({
      variants: [],
      localUri: "file:///tmp/local.jpg",
      pending: false,
    });
    assert.deepEqual(done, { kind: "none" });
  });

  it("does not accept color strings as image sources", () => {
    const resolved = resolveVibeMediaSource({
      variants: [
        {
          variant_type: "feed",
          mime_type: "image/jpeg",
          url: "#5996CF",
          expires_at: "2099-01-01T00:00:00Z",
        },
      ],
      localUri: null,
      pending: false,
    });
    assert.deepEqual(resolved, { kind: "none" });
  });
});

describe("reconcileVibeFeed", () => {
  it("replaces optimistic rows once the server item arrives", () => {
    const serverItems = [
      {
        id: "server-1",
        venue_id: "v1",
        media_type: "image" as const,
        attribution_mode: "attributed" as const,
        author: null,
        author_label: "Alpha",
        caption: null,
        vibe_tags: [],
        published_at: "2026-07-25T20:00:00Z",
        expires_at: "2026-07-26T08:00:00Z",
        variants: [
          {
            variant_type: "feed",
            mime_type: "image/jpeg",
            url: "https://cdn.example/a.jpg",
            expires_at: "2099-01-01T00:00:00Z",
          },
        ],
        viewer_is_author: true,
      },
    ];
    const merged = reconcileVibeFeed({
      serverItems,
      optimistic: [
        {
          kind: "optimistic",
          id: "optimistic:req-1",
          clientRequestId: "req-1",
          liveVibeId: "server-1",
          localUri: "file:///tmp/local.jpg",
          caption: null,
          vibeTags: [],
          authorLabel: "You",
          publishedAt: "2026-07-25T20:00:00Z",
          expiresAt: "2026-07-26T08:00:00Z",
          status: "processing",
        },
      ],
    });
    assert.equal(merged.length, 1);
    assert.equal(merged[0]?.kind, "server");
    assert.equal(merged[0]?.id, "server-1");
  });

  it("keeps a single optimistic row before server creation", () => {
    const merged = reconcileVibeFeed({
      serverItems: [],
      optimistic: [
        {
          kind: "optimistic",
          id: "optimistic:req-1",
          clientRequestId: "req-1",
          liveVibeId: null,
          localUri: "file:///tmp/local.jpg",
          caption: null,
          vibeTags: [],
          authorLabel: "You",
          publishedAt: "2026-07-25T20:00:00Z",
          expiresAt: "2026-07-26T08:00:00Z",
          status: "uploading",
        },
      ],
    });
    assert.equal(merged.length, 1);
    assert.equal(merged[0]?.kind, "optimistic");
  });
});

describe("Experience post-publish layout contracts", () => {
  const card = read("src/features/experience/LiveVibeCard.tsx");
  const screen = read("src/features/experience/ExperienceScreen.tsx");
  const media = read("src/features/experience/vibeMedia.ts");
  const fixture = path.join(mobileRoot, "assets/fixtures/sample-vibe.jpg");

  it("uses a finite 4/5 media aspect ratio without flex:1 media", () => {
    assert.equal(LIVE_VIBE_MEDIA_ASPECT_RATIO, 4 / 5);
    assert.match(media, /LIVE_VIBE_MEDIA_ASPECT_RATIO = 4 \/ 5/);
    assert.match(card, /aspectRatio: LIVE_VIBE_MEDIA_ASPECT_RATIO/);
    assert.doesNotMatch(card, /mediaFrame:[\s\S]*flex:\s*1/);
    assert.doesNotMatch(card, /Dimensions\.get/);
    assert.doesNotMatch(card, /height:\s*["']100%["']/);
    assert.doesNotMatch(card, /minHeight:\s*\d{3,}/);
  });

  it("resets composer after publish and hides permanent progress", () => {
    assert.match(screen, /resetComposer/);
    assert.match(screen, /Live Vibe published/);
    assert.match(screen, /showUploadPercent/);
    assert.match(screen, /phase === "uploading"/);
    assert.match(screen, /invalidateQueries\(\{\s*queryKey:\s*\["vibes", venueId\]/);
    assert.match(screen, /\["venue", venueId, "vibes-preview"\]/);
    assert.match(screen, /reconcileVibeFeed/);
  });

  it("renders noir fallback instead of a blue placeholder", () => {
    assert.match(card, /Couldn’t load this vibe/);
    assert.match(card, /#111111/);
    assert.doesNotMatch(card, /#5996CF|blue/i);
    assert.doesNotMatch(screen, /source=\{\{\s*uri:\s*["']#/);
  });

  it("uses a real bundled JPEG fixture for development uploads", () => {
    assert.equal(existsSync(fixture), true);
    const size = readFileSync(fixture).byteLength;
    assert.ok(size > 10_000, `fixture should be a real image, got ${size} bytes`);
    assert.match(
      read("src/features/experience/uploadHelpers.ts"),
      /sample-vibe\.jpg/,
    );
    assert.match(screen, /__DEV__/);
  });

  it("keeps FlatList scrolling with header composition", () => {
    assert.match(screen, /ListHeaderComponent=\{listHeader\}/);
    assert.match(screen, /style=\{styles\.list\}/);
    assert.match(screen, /list:\s*\{\s*flex:\s*1/);
    assert.doesNotMatch(screen, /cardMedia:[\s\S]*flex:\s*1/);
  });
});
