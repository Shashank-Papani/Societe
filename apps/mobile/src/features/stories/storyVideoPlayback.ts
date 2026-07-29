/**
 * Pure Story video playback helpers — testable without mounting expo-video.
 */

export type VideoPlaybackDecision = {
  shouldPlay: boolean;
  reason:
    | "inactive"
    | "paused"
    | "no_source"
    | "buffering_keep_paused"
    | "play";
};

export function decideVideoPlayback(params: {
  active: boolean;
  paused: boolean;
  hasSource: boolean;
  status: "idle" | "loading" | "readyToPlay" | "error" | string;
}): VideoPlaybackDecision {
  if (!params.active) {
    return { shouldPlay: false, reason: "inactive" };
  }
  if (!params.hasSource) {
    return { shouldPlay: false, reason: "no_source" };
  }
  if (params.paused) {
    return { shouldPlay: false, reason: "paused" };
  }
  if (params.status === "error") {
    return { shouldPlay: false, reason: "no_source" };
  }
  return { shouldPlay: true, reason: "play" };
}

/** Returns null when duration is unknown — callers must freeze progress. */
export function computeVideoProgressFraction(
  currentTimeSec: number,
  durationSec: number,
): number | null {
  if (!Number.isFinite(currentTimeSec) || !Number.isFinite(durationSec)) {
    return null;
  }
  if (durationSec <= 0) {
    return null;
  }
  if (currentTimeSec < 0) {
    return 0;
  }
  return Math.min(1, currentTimeSec / durationSec);
}

export function shouldAdvanceAfterVideoComplete(params: {
  active: boolean;
  buffering: boolean;
}): boolean {
  return params.active && !params.buffering;
}

export function shouldRecordStoryView(params: {
  mediaType: "image" | "video";
  alreadyRecorded: boolean;
  visibleMs: number;
  playbackStarted: boolean;
  viewDelayMs: number;
}): boolean {
  if (params.alreadyRecorded) {
    return false;
  }
  if (params.mediaType === "video") {
    // Poster-only preload must never count as a view.
    if (!params.playbackStarted) {
      return false;
    }
    return params.visibleMs >= params.viewDelayMs;
  }
  return params.visibleMs >= params.viewDelayMs;
}

export function canRefreshSignedMediaUrl(params: {
  storyId: string;
  alreadyRetried: ReadonlySet<string>;
}): boolean {
  return !params.alreadyRetried.has(params.storyId);
}

export function markSignedMediaUrlRetry(
  alreadyRetried: ReadonlySet<string>,
  storyId: string,
): Set<string> {
  const next = new Set(alreadyRetried);
  next.add(storyId);
  return next;
}
