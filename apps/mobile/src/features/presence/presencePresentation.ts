/**
 * Pure Presence presentation helpers — truthful data only.
 */

import { formatVenueTypeTitle } from "@/features/discover/discoverPresentation";
import { formatPresenceDistance } from "@/features/presence/presenceEligibility";
import { projectVenuePins } from "@/features/presence/presenceGeometry";

export { projectVenuePins };

export const PRESENCE_LOCATION_TO_STORIES_GAP = 16;
export const PRESENCE_STORY_ITEM_WIDTH = 80;
export const PRESENCE_STORY_IMAGE = 62;
export const PRESENCE_STORY_RING = 68;
export const PRESENCE_STORY_NAME_SIZE = 14;
export const PRESENCE_STORY_GAP = 12;
export const PRESENCE_MAP_HEIGHT = 220;

export const PRESENCE_SURFACE = {
  page: "#000000",
  card: "#0A0A0A",
  border: "rgba(255,255,255,0.07)",
  map: "#0C0E0D",
  pinMuted: "#6B7280",
  lime: "#B9F908",
  ringInactive: "rgba(255,255,255,0.30)",
} as const;

export type PresencePerson = {
  user_id: string;
  handle: string;
  display_name: string;
  profile_photo_url?: string | null;
};

export function formatPresenceMetaLine(input: {
  category: string;
  distance_m?: number;
  /** Real aggregate only — omit when unknown. */
  hereNowCount?: number | null;
}): string {
  const parts = [formatVenueTypeTitle(input.category)];
  const distance = formatPresenceDistance(input.distance_m);
  if (distance) {
    parts.push(distance);
  }
  if (typeof input.hereNowCount === "number" && Number.isFinite(input.hereNowCount)) {
    parts.push(`${Math.max(0, Math.round(input.hereNowCount))} here now`);
  }
  return parts.join(" • ");
}

export function visiblePeopleForStack(
  people: PresencePerson[],
  maxVisible = 4,
): { visible: PresencePerson[]; overflow: number } {
  const visible = people.slice(0, maxVisible);
  const overflow = Math.max(0, people.length - visible.length);
  return { visible, overflow };
}

export function presenceAvatarAccessibilityLabel(
  venueName: string,
  count: number,
): string {
  if (count <= 0) {
    return `No visible people at ${venueName}`;
  }
  if (count === 1) {
    return `1 visible person at ${venueName}`;
  }
  return `${count} visible people at ${venueName}`;
}

/** Large green fills that must not appear in Presence content styles. */
export const PRESENCE_FORBIDDEN_GREEN_FILLS = [
  "rgba(20, 26, 22",
  "colors.surfaceGlass",
  "colors.backgroundSecondary",
  "colors.surfaceSolid",
  "colors.surfacePressed",
] as const;
