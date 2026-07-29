import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { VIEW_RECORD_DELAY_MS, shouldRecordView } from "./storyHelpers.ts";
import {
  canRefreshSignedMediaUrl,
  computeVideoProgressFraction,
  decideVideoPlayback,
  markSignedMediaUrlRetry,
  shouldAdvanceAfterVideoComplete,
  shouldRecordStoryView,
} from "./storyVideoPlayback.ts";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

function read(rel: string): string {
  return readFileSync(path.join(mobileRoot, rel), "utf8");
}

describe("decideVideoPlayback", () => {
  it("does not play when inactive", () => {
    const decision = decideVideoPlayback({
      active: false,
      paused: false,
      hasSource: true,
      status: "readyToPlay",
    });
    assert.equal(decision.shouldPlay, false);
    assert.equal(decision.reason, "inactive");
  });

  it("plays when active and not paused", () => {
    const decision = decideVideoPlayback({
      active: true,
      paused: false,
      hasSource: true,
      status: "readyToPlay",
    });
    assert.equal(decision.shouldPlay, true);
    assert.equal(decision.reason, "play");
  });

  it("pauses on hold / explicit pause", () => {
    const decision = decideVideoPlayback({
      active: true,
      paused: true,
      hasSource: true,
      status: "readyToPlay",
    });
    assert.equal(decision.shouldPlay, false);
    assert.equal(decision.reason, "paused");
  });
});

describe("video progress and buffering", () => {
  it("freezes progress when duration is unknown", () => {
    assert.equal(computeVideoProgressFraction(1.2, 0), null);
    assert.equal(computeVideoProgressFraction(1.2, Number.NaN), null);
    assert.equal(computeVideoProgressFraction(Number.NaN, 10), null);
  });

  it("computes finite progress from playable position", () => {
    assert.equal(computeVideoProgressFraction(5, 10), 0.5);
    assert.equal(computeVideoProgressFraction(12, 10), 1);
  });

  it("does not advance while buffering", () => {
    assert.equal(
      shouldAdvanceAfterVideoComplete({ active: true, buffering: true }),
      false,
    );
  });

  it("advances after playback completes when active", () => {
    assert.equal(
      shouldAdvanceAfterVideoComplete({ active: true, buffering: false }),
      true,
    );
  });
});

describe("video view recording", () => {
  it("does not record during poster-only preload", () => {
    assert.equal(
      shouldRecordStoryView({
        mediaType: "video",
        alreadyRecorded: false,
        visibleMs: 5_000,
        playbackStarted: false,
        viewDelayMs: VIEW_RECORD_DELAY_MS,
      }),
      false,
    );
    assert.equal(
      shouldRecordView({
        visibleMs: 5_000,
        mediaType: "video",
        alreadyRecorded: false,
        playbackStarted: false,
      }),
      false,
    );
  });

  it("records one view after genuine playback and delay", () => {
    assert.equal(
      shouldRecordStoryView({
        mediaType: "video",
        alreadyRecorded: false,
        visibleMs: VIEW_RECORD_DELAY_MS,
        playbackStarted: true,
        viewDelayMs: VIEW_RECORD_DELAY_MS,
      }),
      true,
    );
  });

  it("prevents duplicate view recording", () => {
    assert.equal(
      shouldRecordStoryView({
        mediaType: "video",
        alreadyRecorded: true,
        visibleMs: 10_000,
        playbackStarted: true,
        viewDelayMs: VIEW_RECORD_DELAY_MS,
      }),
      false,
    );
  });
});

describe("signed URL refresh", () => {
  it("allows a single refresh then blocks repeats", () => {
    const storyId = "11111111-1111-4111-8111-111111111111";
    assert.equal(canRefreshSignedMediaUrl({ storyId, alreadyRetried: new Set() }), true);
    const once = markSignedMediaUrlRetry(new Set(), storyId);
    assert.equal(canRefreshSignedMediaUrl({ storyId, alreadyRetried: once }), false);
  });
});

describe("Story video wiring contracts", () => {
  const slide = read("src/features/stories/StoryVideoSlide.tsx");
  const viewer = read("src/features/stories/StoryViewerModal.tsx");

  it("uses expo-video and only mounts the active slide player", () => {
    assert.match(slide, /useVideoPlayer/);
    assert.match(slide, /VideoView/);
    assert.match(slide, /player\.play\(/);
    assert.match(slide, /player\.pause\(/);
    assert.match(viewer, /StoryVideoSlide/);
    assert.match(viewer, /videoUri=\{videoVariant\.url\}/);
    assert.match(viewer, /slide\.media_type !== "image"/);
    assert.match(viewer, /onPlaybackComplete=\{goNextSlide\}/);
  });

  it("pauses for hold, background, menus and cleans up on unmount", () => {
    assert.match(viewer, /holdPaused/);
    assert.match(viewer, /appInactive/);
    assert.match(viewer, /setAppInactive\(next !== "active"\)/);
    assert.match(slide, /return \(\) => \{[\s\S]*player\.pause\(/);
    assert.match(slide, /playToEnd/);
    assert.match(slide, /status === "loading"/);
  });

  it("keeps poster while initializing and offers retry without logging URLs", () => {
    assert.match(slide, /story-video-poster/);
    assert.match(slide, /onFirstFrameRender/);
    assert.match(slide, /story-video-retry/);
    assert.doesNotMatch(slide, /console\.(log|warn|error)\([^\)]*uri/i);
    assert.doesNotMatch(viewer, /console\.(log|warn|error)\([^\)]*url/i);
  });

  it("records views only after playbackStarted for videos", () => {
    assert.match(viewer, /playbackStarted/);
    assert.match(viewer, /onPlaybackStarted/);
    assert.match(viewer, /recordViewIfNeeded\(storyId, "video", true\)/);
  });
});
