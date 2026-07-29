/**
 * Pure Story helpers — lifecycle mapping, media URL picks, CTA safety, rail math.
 */

import type { MediaVariant, StoryGroupSummary, StorySlide, StoryUploadResponse } from "./storySchemas";

export type StoryUploadPhase =
  | "idle"
  | "picking"
  | "permission_denied"
  | "cancelled"
  | "preparing"
  | "creating_intent"
  | "uploading"
  | "completing"
  | "processing"
  | "moderation_pending"
  | "published"
  | "rejected"
  | "failed"
  | "upload_expired"
  | "unavailable";

export const STORY_TERMINAL_LIFECYCLES = new Set([
  "ready",
  "invalid",
  "rejected",
  "processing_failed",
  "upload_expired",
  "revoked",
  "deleted",
]);

export const STORY_TERMINAL_PUBLICATIONS = new Set([
  "published",
  "rejected",
  "failed",
  "expired",
  "deleted",
  "hidden",
]);

export const IMAGE_SLIDE_DURATION_MS = 5_000;
export const VIEW_RECORD_DELAY_MS = 1_000;

export function mapStoryUploadPhase(
  lifecycle: string,
  publication: string,
  moderation: string,
): StoryUploadPhase {
  if (publication === "published" || lifecycle === "ready") {
    return "published";
  }
  if (lifecycle === "upload_expired") {
    return "upload_expired";
  }
  if (lifecycle === "rejected" || publication === "rejected" || moderation === "rejected") {
    return "rejected";
  }
  if (
    lifecycle === "invalid" ||
    lifecycle === "processing_failed" ||
    publication === "failed"
  ) {
    return "failed";
  }
  if (lifecycle === "moderation_pending" || publication === "moderation_pending") {
    return "moderation_pending";
  }
  if (
    lifecycle === "processing" ||
    lifecycle === "validating" ||
    lifecycle === "uploaded" ||
    publication === "processing"
  ) {
    return "processing";
  }
  return "processing";
}

export function isStoryUploadTerminal(status: StoryUploadResponse): boolean {
  return (
    STORY_TERMINAL_LIFECYCLES.has(status.lifecycle_status) ||
    STORY_TERMINAL_PUBLICATIONS.has(status.publication_status)
  );
}

export function pickStoryDisplayVariant(
  variants: MediaVariant[],
  mediaType: "image" | "video",
): MediaVariant | null {
  if (variants.length === 0) {
    return null;
  }
  if (mediaType === "video") {
    return pickStoryPosterVariant(variants);
  }
  const preferred = ["story", "feed", "feed_poster", "original_display", "thumbnail"];
  for (const type of preferred) {
    const hit = variants.find((v) => v.variant_type === type);
    if (hit) {
      return hit;
    }
  }
  const image = variants.find((v) => v.mime_type.startsWith("image/"));
  return image ?? variants[0] ?? null;
}

/** Poster/thumbnail for video slides while the player initializes. */
export function pickStoryPosterVariant(variants: MediaVariant[]): MediaVariant | null {
  const preferred = ["story_poster", "feed_poster", "poster", "thumbnail"];
  for (const type of preferred) {
    const hit = variants.find((v) => v.variant_type === type);
    if (hit) {
      return hit;
    }
  }
  return variants.find((v) => v.mime_type.startsWith("image/")) ?? null;
}

/** Playable video variant for Story playback. */
export function pickStoryVideoVariant(variants: MediaVariant[]): MediaVariant | null {
  const preferred = ["story", "feed", "original", "original_display", "video"];
  for (const type of preferred) {
    const hit = variants.find(
      (v) => v.variant_type === type && v.mime_type.startsWith("video/"),
    );
    if (hit) {
      return hit;
    }
  }
  return variants.find((v) => v.mime_type.startsWith("video/")) ?? null;
}

export function storyGroupAccessibilityLabel(group: StoryGroupSummary): string {
  const official = group.is_official ? "Official. " : "";
  const viewed =
    group.unviewed_count > 0
      ? `${group.unviewed_count} unviewed of ${group.active_count}.`
      : `All ${group.active_count} viewed.`;
  return `${official}${group.author_label}. ${viewed}`;
}

export function applyOptimisticView(
  groups: StoryGroupSummary[],
  storyId: string,
  groupKey: string,
): StoryGroupSummary[] {
  return groups.map((group) => {
    if (group.group_key !== groupKey) {
      return group;
    }
    const nextUnviewed = Math.max(0, group.unviewed_count - 1);
    return { ...group, unviewed_count: nextUnviewed };
  });
}

export function removeStoryFromDetail(
  detail: { slides: StorySlide[]; group_key: string },
  storyId: string,
): { slides: StorySlide[]; empty: boolean } {
  const slides = detail.slides.filter((s) => s.story_id !== storyId);
  return { slides, empty: slides.length === 0 };
}

/** Only https URLs are eligible for in-app open confirmation. */
export function isSafeExternalCtaUrl(url: string | null | undefined): boolean {
  if (!url) {
    return false;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function officialPostTypeLabel(postType: string): string {
  switch (postType) {
    case "announcement":
      return "Announcement";
    case "event":
      return "Event";
    case "dj":
      return "DJ";
    case "special":
      return "Special";
    case "policy":
      return "Policy";
    case "promotion":
      return "Promotion";
    case "general":
      return "Update";
    default:
      return "Update";
  }
}

export function formatRelativeExpiry(expiresAt: string, nowMs = Date.now()): string {
  const expires = Date.parse(expiresAt);
  if (!Number.isFinite(expires)) {
    return "";
  }
  const hours = Math.max(0, Math.round((expires - nowMs) / 3_600_000));
  if (hours <= 0) {
    return "Expiring soon";
  }
  if (hours === 1) {
    return "1 hour left";
  }
  return `${hours} hours left`;
}

export function shouldRecordView(params: {
  visibleMs: number;
  mediaType: "image" | "video";
  alreadyRecorded: boolean;
  playbackStarted?: boolean;
}): boolean {
  if (params.alreadyRecorded) {
    return false;
  }
  if (params.mediaType === "video") {
    if (!params.playbackStarted) {
      return false;
    }
    return params.visibleMs >= VIEW_RECORD_DELAY_MS;
  }
  return params.visibleMs >= VIEW_RECORD_DELAY_MS;
}
