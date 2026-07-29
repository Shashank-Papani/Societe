import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  formatVibeTagLabel,
  resolveVibeDisplayState,
  vibeDisplayLabel,
} from "./vibeLifecycle.ts";

describe("Live Vibe lifecycle labels", () => {
  it("labels live vibes before expiry", () => {
    const now = Date.parse("2026-07-25T22:00:00Z");
    assert.equal(
      resolveVibeDisplayState({
        publishedAt: "2026-07-25T21:00:00Z",
        expiresAt: "2026-07-26T13:00:00Z",
        nowMs: now,
      }),
      "LIVE",
    );
    assert.equal(vibeDisplayLabel("LIVE"), "LIVE");
  });

  it("does not label expired vibes as LIVE", () => {
    const now = Date.parse("2026-07-26T14:00:00Z");
    assert.equal(
      resolveVibeDisplayState({
        publishedAt: "2026-07-25T21:00:00Z",
        expiresAt: "2026-07-26T13:00:00Z",
        nowMs: now,
      }),
      "RECENT",
    );
    assert.equal(vibeDisplayLabel("RECENT"), "RECENT VIBE");
  });

  it("formats vibe tags for display", () => {
    assert.equal(formatVibeTagLabel("high_energy"), "High Energy");
  });
});
