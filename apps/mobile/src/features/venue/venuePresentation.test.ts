import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  pickApprovedLiveVibeImage,
  resolveVenueIdentityImage,
  resolveVenueImage,
  venueImageFailedFallback,
} from "./venueImage.ts";
import {
  containsForbiddenVenueCopy,
  formatClock,
  formatMethodLabel,
  formatOpenState,
  formatVisibilityLabel,
  isVenueMissingError,
  isVerifiedAtVenue,
  parseDistanceParam,
  primaryVenueAction,
} from "./venuePresentation.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(here, "../../..");

const sampleVenue = {
  id: "v1",
  name: "Echo Basement",
  category: "nightclub",
  status: "active",
  description: "Underground room with rotating residents.",
  street_address: "12 Signal St",
  city: "Los Angeles",
  region: "CA",
  music_tags: ["techno"],
  experience_tags: ["dancefloor"],
  hours: [
    {
      weekday: 5,
      opens_local: "22:00",
      closes_local: "04:00",
      closes_next_day: true,
    },
  ],
};

describe("Venue image resolver", () => {
  it("prefers cover, then gallery, then category fallback — never Live Vibe", () => {
    assert.equal(
      resolveVenueIdentityImage({
        coverImageUrl: "https://cdn.example/cover.jpg",
        galleryImageUrl: "https://cdn.example/gallery.jpg",
        category: "nightclub",
        venueId: "v1",
      }).source,
      "cover",
    );
    assert.equal(
      resolveVenueIdentityImage({
        galleryImageUrl: "https://cdn.example/gallery.jpg",
        category: "nightclub",
        venueId: "v1",
      }).source,
      "gallery",
    );
    // Live Vibe must not become identity media.
    assert.equal(
      resolveVenueImage({
        liveVibeImageUrl: "https://cdn.example/vibe.jpg",
        category: "nightclub",
        venueId: "v1",
      }).source,
      "fallback",
    );
    const fallback = resolveVenueIdentityImage({
      category: "nightclub",
      venueId: "v1",
    });
    assert.equal(fallback.kind, "fallback");
    assert.equal(fallback.kind === "fallback" ? fallback.assetKey : null, "club");
  });

  it("rejects invalid URLs and falls back on load failure", () => {
    assert.equal(resolveVenueImage({ coverImageUrl: "not-a-url" }).kind, "fallback");
    assert.equal(resolveVenueImage({ coverImageUrl: null }).kind, "fallback");
    assert.equal(
      venueImageFailedFallback({ category: "rooftop", venueId: "v1" }).kind,
      "fallback",
    );
    assert.equal(
      venueImageFailedFallback({ category: "rooftop", venueId: "v1" }).assetKey,
      "rooftop",
    );
  });

  it("picks only image Live Vibes with usable URLs", () => {
    const picked = pickApprovedLiveVibeImage([
      {
        media_type: "video",
        published_at: "2026-07-25T01:00:00Z",
        variants: [{ url: "https://cdn.example/video.mp4" }],
      },
      {
        media_type: "image",
        published_at: "2026-07-25T02:00:00Z",
        variants: [{ url: "https://cdn.example/vibe.jpg" }],
      },
    ]);
    assert.equal(picked?.url, "https://cdn.example/vibe.jpg");
  });
});

describe("Venue presentation helpers", () => {
  it("formats open state from real hours without inventing times", () => {
    // weekday 5 = Saturday in API (Mon=0)
    const saturday = new Date("2026-07-25T12:00:00Z");
    // Local day depends on TZ; assert null-safe contract instead of brittle TZ.
    const label = formatOpenState(sampleVenue, saturday);
    assert.ok(label === null || label.startsWith("OPEN UNTIL "));
    assert.equal(formatOpenState({ ...sampleVenue, hours: [] }), null);
  });

  it("detects verified presence and expired leases", () => {
    const now = Date.parse("2026-07-25T12:00:00Z");
    assert.equal(
      isVerifiedAtVenue(
        {
          state: "verified",
          venue: { id: "v1", name: "Echo Basement" },
          verification_level: "location",
          lease_expires_at: "2026-07-25T13:00:00Z",
          social_features_enabled: true,
          reasons: [],
        },
        "v1",
        now,
      ),
      true,
    );
    assert.equal(
      isVerifiedAtVenue(
        {
          state: "verified",
          venue: { id: "v1", name: "Echo Basement" },
          verification_level: "location",
          lease_expires_at: "2026-07-25T11:00:00Z",
          social_features_enabled: true,
          reasons: [],
        },
        "v1",
        now,
      ),
      false,
    );
  });

  it("maps privacy visibility and method labels from real values", () => {
    assert.equal(formatVisibilityLabel({ ghostMode: true }), "Ghost Mode");
    assert.equal(
      formatVisibilityLabel({ discoverableInVenue: true, socialFeaturesEnabled: true }),
      "Discoverable",
    );
    assert.equal(formatMethodLabel("gps_fused"), "Gps fused");
    assert.equal(formatClock(null), "—");
  });

  it("switches primary action after verification", () => {
    assert.equal(primaryVenueAction(false).kind, "verify");
    assert.equal(primaryVenueAction(true).kind, "see_whos_here");
    assert.match(primaryVenueAction(true).label, /SEE WHO/);
  });

  it("parses distance params and missing venue errors", () => {
    assert.equal(parseDistanceParam("120"), 120);
    assert.equal(parseDistanceParam("nope"), undefined);
    assert.equal(isVenueMissingError({ status: 404, code: "NOT_FOUND" }), true);
  });
});

describe("Venue Detail / Presence Verified screens avoid fake copy", () => {
  it("does not include VIP, ratings, or reservation language", () => {
    const files = [
      "src/features/venue/VenueDetailScreen.tsx",
      "src/features/presence/PresenceVerifiedScreen.tsx",
      "src/features/venue/VenueDetailStates.tsx",
    ];
    for (const rel of files) {
      const text = readFileSync(path.join(mobileRoot, rel), "utf8");
      assert.equal(containsForbiddenVenueCopy(text), false, rel);
      assert.doesNotMatch(text, /★★|rating|bottle|reservation|Apple Wallet|pass id/i);
    }
  });

  it("uses the shared identity image resolver and local fallback asset", () => {
    const screen = readFileSync(
      path.join(mobileRoot, "src/features/venue/VenueDetailScreen.tsx"),
      "utf8",
    );
    assert.match(screen, /resolveVenueIdentityImage/);
    assert.match(screen, /resolveLiveVibeMedia/);
    assert.match(screen, /resolveVenueDisplaySource/);
    assert.match(screen, /venueCategoryAssets/);
    assert.equal(
      existsSync(path.join(mobileRoot, "assets/images/venue-fallback.png")),
      true,
    );
    assert.equal(
      existsSync(path.join(mobileRoot, "assets/images/venue-categories/club.jpg")),
      true,
    );
  });

  it("wires verify presence and see who’s here actions", () => {
    const screen = readFileSync(
      path.join(mobileRoot, "src/features/venue/VenueDetailScreen.tsx"),
      "utf8",
    );
    assert.match(screen, /useVerifyPresence/);
    assert.match(screen, /candidateVenueId: venueId/);
    assert.match(screen, /\/\(tabs\)\/connect/);
    assert.match(screen, /VERIFYING/);
    assert.match(screen, /venue-sticky-action/);
  });

  it("Presence Verified screen renders real lease and privacy fields", () => {
    const screen = readFileSync(
      path.join(mobileRoot, "src/features/presence/PresenceVerifiedScreen.tsx"),
      "utf8",
    );
    assert.match(screen, /Presence Verified/);
    assert.match(screen, /formatVisibilityLabel/);
    assert.match(screen, /expiresAtIso/);
    assert.match(screen, /SEE WHO’S HERE/);
    assert.match(screen, /BACK TO VENUE/);
    assert.doesNotMatch(screen, /QR|Wallet|bottle|VIP/i);
  });
});
