/**
 * Client presentation of Live Vibe lifecycle.
 * Prefer server-derived display_state when the API adds it; until then derive
 * from published_at / expires_at without inventing crowd metrics.
 */

export type VibeDisplayState = "LIVE" | "RECENT" | "ARCHIVED";

export function resolveVibeDisplayState(input: {
  publishedAt: string;
  expiresAt: string;
  nowMs?: number;
}): VibeDisplayState {
  const now = input.nowMs ?? Date.now();
  const expires = Date.parse(input.expiresAt);
  const published = Date.parse(input.publishedAt);
  if (Number.isFinite(expires) && now < expires) {
    return "LIVE";
  }
  const sevenDaysMs = 7 * 24 * 60 * 60 * 1000;
  if (Number.isFinite(published) && now - published < sevenDaysMs) {
    return "RECENT";
  }
  return "ARCHIVED";
}

export function vibeDisplayLabel(state: VibeDisplayState): string {
  switch (state) {
    case "LIVE":
      return "LIVE";
    case "RECENT":
      return "RECENT VIBE";
    case "ARCHIVED":
      return "ARCHIVED";
  }
}

export function formatVibeTagLabel(tag: string): string {
  return tag
    .trim()
    .toLowerCase()
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
