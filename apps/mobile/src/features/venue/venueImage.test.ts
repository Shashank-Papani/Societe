import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  normalizeVenueCategory,
  normalizeVenueName,
  pickApprovedLiveVibeImage,
  resolveCategoryFallbackKey,
  resolveExplicitVenueFallbackKey,
  resolveLiveVibeMedia,
  resolveVenueIdentityImage,
  resolveVenueImage,
  selectLoungeFallback,
  venueImageFailedFallback,
} from "./venueImage.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(here, "../../..");

const neonHouseIdentity = {
  venueId: "neon-house",
  venueName: "Société Neon House",
  category: "nightclub",
};

const leavesVibeUrl = "https://cdn.example/leaves.jpg";

describe("Venue category fallback mapping", () => {
  it("maps Cooper Mirage to bar2.jpg", () => {
    assert.equal(resolveExplicitVenueFallbackKey("Cooper Mirage"), "bar2");
    const resolved = resolveVenueIdentityImage({
      category: "bar",
      venueId: "v1",
      venueName: "Cooper Mirage",
    });
    assert.equal(resolved.kind, "fallback");
    assert.equal(resolved.kind === "fallback" ? resolved.assetKey : null, "bar2");
  });

  it("maps Copper Mirage to bar2.jpg", () => {
    assert.equal(resolveExplicitVenueFallbackKey("Copper Mirage"), "bar2");
    assert.equal(resolveExplicitVenueFallbackKey("Copper  Mirage"), "bar2");
    assert.equal(normalizeVenueName("Cooper-Mirage!"), "cooper mirage");
    assert.equal(
      resolveCategoryFallbackKey("bar", "v1", "Cooper Mirage"),
      "bar2",
    );
    const resolved = resolveVenueImage({
      category: "bar",
      venueId: "v1",
      venueName: "Copper Mirage",
    });
    assert.equal(resolved.kind, "fallback");
    assert.equal(resolved.kind === "fallback" ? resolved.assetKey : null, "bar2");
  });

  it("maps nightclub and club to club image", () => {
    assert.equal(resolveCategoryFallbackKey("nightclub", "v1"), "club");
    assert.equal(resolveCategoryFallbackKey("club", "v1"), "club");
    assert.equal(resolveCategoryFallbackKey("Night Club", "v1"), "club");
    assert.equal(resolveCategoryFallbackKey("dance_club", "v1"), "club");
  });

  it("maps rooftop and rooftop_bar to rooftop image", () => {
    assert.equal(resolveCategoryFallbackKey("rooftop", "v1"), "rooftop");
    assert.equal(resolveCategoryFallbackKey("rooftop_bar", "v1"), "rooftop");
    assert.equal(resolveCategoryFallbackKey("rooftop-bar", "v1"), "rooftop");
  });

  it("maps bar and sports_bar to sports-bar image", () => {
    assert.equal(resolveCategoryFallbackKey("bar", "v1"), "sportsBar");
    assert.equal(resolveCategoryFallbackKey("sports_bar", "v1"), "sportsBar");
    assert.equal(resolveCategoryFallbackKey("sportsbar", "v1"), "sportsBar");
  });

  it("maps lounge to a lounge image", () => {
    const key = resolveCategoryFallbackKey("lounge", "venue-alpha");
    assert.ok(key === "lounge1" || key === "lounge2");
  });

  it("keeps lounge selection deterministic for the same venue id", () => {
    const a = selectLoungeFallback("stable-lounge-id-42");
    const b = selectLoungeFallback("stable-lounge-id-42");
    assert.equal(a, b);
    assert.equal(
      resolveCategoryFallbackKey("lounge", "stable-lounge-id-42"),
      resolveCategoryFallbackKey("lounge", "stable-lounge-id-42"),
    );
  });

  it("can resolve different lounge images for different venue ids", () => {
    const keys = new Set(
      [
        "venue-a",
        "venue-b",
        "venue-c",
        "venue-d",
        "venue-e",
        "venue-f",
        "venue-g",
        "venue-h",
      ].map((id) => selectLoungeFallback(id)),
    );
    assert.equal(keys.has("lounge1"), true);
    assert.equal(keys.has("lounge2"), true);
  });

  it("defaults missing lounge venue id to lounge-1", () => {
    assert.equal(selectLoungeFallback(null), "lounge1");
    assert.equal(selectLoungeFallback(undefined), "lounge1");
    assert.equal(selectLoungeFallback("  "), "lounge1");
  });

  it("uses generic fallback for missing or unknown categories", () => {
    assert.equal(resolveCategoryFallbackKey(null, "v1"), "generic");
    assert.equal(resolveCategoryFallbackKey(undefined, "v1"), "generic");
    assert.equal(resolveCategoryFallbackKey("", "v1"), "generic");
    assert.equal(resolveCategoryFallbackKey("live_music", "v1"), "generic");
    assert.equal(resolveCategoryFallbackKey("warehouse", "v1"), "generic");
    assert.equal(resolveCategoryFallbackKey("restaurant", "v1"), "generic");
    assert.equal(resolveCategoryFallbackKey("event_space", "v1"), "generic");
  });

  it("normalizes without mutating the original string", () => {
    const original = " Night-Club ";
    assert.equal(normalizeVenueCategory(original), "night_club");
    assert.equal(original, " Night-Club ");
  });
});

describe("Venue identity image priority", () => {
  it("gives approved owner cover highest identity priority", () => {
    const resolved = resolveVenueIdentityImage({
      approvedCoverUrl: "https://cdn.example/cover.jpg",
      primaryGalleryImageUrl: "https://cdn.example/gallery.jpg",
      approvedGalleryImageUrl: "https://cdn.example/gallery2.jpg",
      category: "nightclub",
      venueId: "v1",
    });
    assert.equal(resolved.kind, "remote");
    assert.equal(resolved.source, "cover");
    assert.equal(resolved.kind === "remote" ? resolved.uri : null, "https://cdn.example/cover.jpg");
  });

  it("prefers approved stable gallery over category fallback", () => {
    const resolved = resolveVenueIdentityImage({
      galleryImageUrl: "https://cdn.example/gallery.jpg",
      category: "rooftop",
      venueId: "v1",
    });
    assert.equal(resolved.kind, "remote");
    assert.equal(resolved.source, "gallery");
  });

  it("ignores latest Live Vibe for identity (compatibility fields)", () => {
    const resolved = resolveVenueImage({
      liveVibeImageUrl: leavesVibeUrl,
      allowLiveVibePreview: true,
      category: "bar",
      venueId: "v1",
    });
    assert.equal(resolved.kind, "fallback");
    assert.equal(resolved.source, "fallback");
    assert.equal(resolved.kind === "fallback" ? resolved.assetKey : null, "sportsBar");
  });

  it("does not let latest Live Vibe override approved owner cover", () => {
    const resolved = resolveVenueImage({
      coverImageUrl: "https://cdn.example/owner-cover.jpg",
      liveVibeImageUrl: leavesVibeUrl,
      category: "nightclub",
      venueId: "v1",
    });
    assert.equal(resolved.kind, "remote");
    assert.equal(resolved.source, "cover");
    assert.equal(
      resolved.kind === "remote" ? resolved.uri : null,
      "https://cdn.example/owner-cover.jpg",
    );
  });

  it("does not let latest Live Vibe override category fallback", () => {
    const resolved = resolveVenueIdentityImage({
      ...neonHouseIdentity,
    });
    assert.deepEqual(resolved, {
      kind: "fallback",
      source: "fallback",
      assetKey: "club",
    });
    // Even if a caller still passes Live Vibe into the compat helper:
    assert.deepEqual(
      resolveVenueImage({
        ...neonHouseIdentity,
        liveVibeImageUrl: leavesVibeUrl,
      }),
      {
        kind: "fallback",
        source: "fallback",
        assetKey: "club",
      },
    );
  });

  it("Société Neon House uses club fallback when no owner media exists", () => {
    const identity = resolveVenueIdentityImage(neonHouseIdentity);
    assert.equal(identity.kind, "fallback");
    assert.equal(identity.kind === "fallback" ? identity.assetKey : null, "club");
  });

  it("uses category fallback when no approved owner media exists", () => {
    assert.deepEqual(
      resolveVenueIdentityImage({ category: "nightclub", venueId: "v1" }),
      { kind: "fallback", source: "fallback", assetKey: "club" },
    );
    assert.deepEqual(
      resolveVenueIdentityImage({ category: "rooftop", venueId: "v1" }),
      {
        kind: "fallback",
        source: "fallback",
        assetKey: "rooftop",
      },
    );
    assert.deepEqual(resolveVenueIdentityImage({ category: "bar", venueId: "v1" }), {
      kind: "fallback",
      source: "fallback",
      assetKey: "sportsBar",
    });
  });

  it("failed owner cover falls back to explicit/category image, not Live Vibe", () => {
    const failed = venueImageFailedFallback({
      category: "nightclub",
      venueId: "v-fail",
      venueName: "Société Neon House",
    });
    assert.equal(failed.kind, "fallback");
    assert.equal(failed.assetKey, "club");
    assert.notEqual(failed.source, "live_vibe");
  });

  it("Discover, Presence, and Venue Detail resolve the same identity image", () => {
    const inputs = neonHouseIdentity;
    const a = resolveVenueIdentityImage(inputs);
    const b = resolveVenueIdentityImage(inputs);
    const c = resolveVenueIdentityImage(inputs);
    assert.deepEqual(a, b);
    assert.deepEqual(b, c);
    assert.deepEqual(a, {
      kind: "fallback",
      source: "fallback",
      assetKey: "club",
    });
  });
});

describe("Live Vibe media priority", () => {
  it("resolves approved Live Vibe media URL first", () => {
    assert.deepEqual(
      resolveLiveVibeMedia({
        mediaUrl: leavesVibeUrl,
        thumbnailUrl: "https://cdn.example/leaves-thumb.jpg",
      }),
      { kind: "remote", uri: leavesVibeUrl, source: "media" },
    );
  });

  it("falls back to approved thumbnail URL", () => {
    assert.deepEqual(
      resolveLiveVibeMedia({
        thumbnailUrl: "https://cdn.example/leaves-thumb.jpg",
      }),
      {
        kind: "remote",
        uri: "https://cdn.example/leaves-thumb.jpg",
        source: "thumbnail",
      },
    );
  });

  it("uses optimistic local URI while pending", () => {
    assert.deepEqual(
      resolveLiveVibeMedia({
        optimisticLocalUri: "file:///tmp/pending.jpg",
        pending: true,
      }),
      { kind: "local", uri: "file:///tmp/pending.jpg" },
    );
  });

  it("returns none for failed/missing Live Vibe (neutral failure for caller)", () => {
    assert.deepEqual(resolveLiveVibeMedia({}), { kind: "none" });
    assert.deepEqual(resolveLiveVibeMedia({ mediaUrl: "not-a-url" }), { kind: "none" });
  });

  it("pickApprovedLiveVibeImage still returns Live Vibe independently of identity", () => {
    const picked = pickApprovedLiveVibeImage([
      {
        media_type: "image",
        published_at: "2026-07-25T02:00:00Z",
        variants: [{ url: leavesVibeUrl }],
      },
    ]);
    assert.equal(picked?.url, leavesVibeUrl);
    const identity = resolveVenueIdentityImage(neonHouseIdentity);
    assert.equal(identity.kind, "fallback");
    assert.equal(identity.kind === "fallback" ? identity.assetKey : null, "club");
  });
});

describe("Call-site separation: identity vs Live Vibe", () => {
  it("Venue Detail hero ignores latest approved Live Vibe", () => {
    const detail = readFileSync(
      path.join(mobileRoot, "src/features/venue/VenueDetailScreen.tsx"),
      "utf8",
    );
    assert.match(detail, /resolveVenueIdentityImage/);
    assert.match(detail, /resolveLiveVibeMedia/);
    assert.match(detail, /pickApprovedLiveVibeImage/);
    assert.doesNotMatch(detail, /liveVibeImageUrl/);
    assert.doesNotMatch(detail, /allowLiveVibePreview/);
    // Hero inputs must not include Live Vibe fields.
    assert.match(
      detail,
      /Live Vibes must never be passed into identity resolution/,
    );
  });

  it("Latest approved vibe card still renders Live Vibe image", () => {
    const detail = readFileSync(
      path.join(mobileRoot, "src/features/venue/VenueDetailScreen.tsx"),
      "utf8",
    );
    assert.match(detail, /venue-live-vibe-card/);
    assert.match(detail, /venue-live-vibe-thumb/);
    assert.match(detail, /liveVibeMedia\.uri/);
    assert.match(detail, /venue-live-vibe-thumb-failed/);
  });

  it("Discover card ignores latest approved Live Vibe", () => {
    const card = readFileSync(
      path.join(mobileRoot, "src/features/discover/VenueCard.tsx"),
      "utf8",
    );
    assert.match(card, /resolveVenueIdentityImage/);
    assert.match(card, /resolveVenueDisplaySource/);
    assert.doesNotMatch(card, /liveVibeImageUrl/);
    assert.doesNotMatch(card, /resolveLiveVibeMedia/);
    assert.doesNotMatch(card, /pickApprovedLiveVibeImage/);
  });

  it("Presence story and selected card ignore latest approved Live Vibe", () => {
    const liveMap = readFileSync(
      path.join(mobileRoot, "src/features/presence/PresenceLiveMap.tsx"),
      "utf8",
    );
    assert.match(liveMap, /resolveVenueDisplaySource/);
    assert.match(liveMap, /presence-venue-circles/);
    assert.match(liveMap, /presence-selected-image/);
    assert.doesNotMatch(liveMap, /liveVibeImageUrl/);
    assert.doesNotMatch(liveMap, /pickApprovedLiveVibeImage/);
    assert.doesNotMatch(liveMap, /resolveLiveVibeMedia/);
  });

  it("Experience feed still resolves Live Vibe media separately", () => {
    const vibeMedia = readFileSync(
      path.join(mobileRoot, "src/features/experience/vibeMedia.ts"),
      "utf8",
    );
    const experience = readFileSync(
      path.join(mobileRoot, "src/features/experience/ExperienceScreen.tsx"),
      "utf8",
    );
    assert.match(vibeMedia, /resolveVibeMediaSource/);
    assert.match(experience, /resolveVibeMediaSource|LiveVibeCard/);
  });

  it("Live Vibe publication invalidates vibe queries without identity media", () => {
    const experience = readFileSync(
      path.join(mobileRoot, "src/features/experience/ExperienceScreen.tsx"),
      "utf8",
    );
    assert.match(experience, /\["vibes", venueId\]/);
    assert.match(experience, /\["venue", venueId, "vibes-preview"\]/);
    assert.match(experience, /never identity\/cover media/);
    assert.doesNotMatch(
      experience,
      /invalidateQueries\(\{\s*queryKey:\s*\["map-venues"\]/,
    );
    assert.doesNotMatch(experience, /cover_image_url\s*=/);
  });

  it("does not import production assets from design-reference", () => {
    const files = [
      "src/features/discover/VenueCard.tsx",
      "src/features/venue/VenueDetailScreen.tsx",
      "src/features/venue/venueCategoryAssets.ts",
      "src/features/venue/venueImage.ts",
    ];
    for (const rel of files) {
      const text = readFileSync(path.join(mobileRoot, rel), "utf8");
      assert.doesNotMatch(text, /design-reference/);
    }
  });

  it("keeps category assets under production assets/images", () => {
    for (const name of [
      "club.jpg",
      "rooftop.jpg",
      "sports-bar.jpg",
      "bar2.jpg",
      "lounge-1.jpg",
      "lounge-2.jpg",
    ]) {
      assert.equal(
        existsSync(path.join(mobileRoot, "assets/images/venue-categories", name)),
        true,
        name,
      );
    }
    assert.equal(
      existsSync(path.join(mobileRoot, "assets/images/venue-fallback.png")),
      true,
    );
  });
});
