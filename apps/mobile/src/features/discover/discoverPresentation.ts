/**
 * Pure Discover presentation helpers — map real venue fields to UI copy.
 * No fake London/VIP/spend/ratings/packed content.
 */

export type VenueLike = {
  id: string;
  name: string;
  category: string;
  city: string;
  region?: string | null;
  distance_m?: number;
  music_tags: string[];
  experience_tags: string[];
  price_band?: number | null;
  /** Optional — only render when API provides a real boolean. */
  is_open?: boolean | null;
  /** Optional numeric packed/crowd 0–100 when API provides it. */
  packed_percent?: number | null;
  /** Optional qualitative crowd label when API provides it (no invented %). */
  crowd_label?: string | null;
};

export type OpenState = {
  label: "Open" | "Closed";
  tone: "open" | "closed";
};

export type MetaSegment = {
  text: string;
  tone: "muted" | "open" | "closed" | "separator";
};

export type CrowdRow =
  | { kind: "percent"; text: string; value: number }
  | { kind: "label"; text: string };

/**
 * Compact vertical rhythm for Discover controls (search → filters).
 * Single source of truth — import this; do not redeclare.
 */
export const DISCOVER_COMPACT_GAP = 10;

/** Discover page uses pure black — local tokens, not global theme rewrite. */
export const discoverSurface = {
  page: "#000000",
  header: "#000000",
  search: "#151515",
  searchBorder: "rgba(255,255,255,0.035)",
  searchPlaceholder: "#777D7A",
  pillInactive: "#121212",
  pillInactiveBorder: "rgba(255,255,255,0.04)",
  pillInactiveText: "#8FA39D",
  settingsFill: "#080808",
  settingsBorder: "rgba(255,255,255,0.06)",
  metaMuted: "#A0AAA6",
  metaSeparator: "#66706C",
  open: "#63D785",
  closed: "#FF6B6B",
  lime: "#B9F908",
  cardAspectRatio: 16 / 9,
  cardRadius: 16,
  cardGap: 14,
} as const;

const VENUE_TYPE_TITLES: Record<string, string> = {
  nightclub: "Nightclub",
  club: "Club",
  rooftop: "Rooftop",
  rooftop_bar: "Rooftop",
  lounge: "Lounge",
  bar: "Bar",
  sports_bar: "Sports Bar",
  warehouse: "Warehouse",
  live_music: "Live Music",
};

const CATEGORY_BADGE_LABELS: Record<string, string> = {
  nightclub: "CLUB",
  bar: "BAR",
  lounge: "LOUNGE",
  rooftop: "ROOFTOP",
  live_music: "LIVE MUSIC",
  warehouse: "WAREHOUSE",
};

/** Compact uppercase badge label (Presence map chips). Discover cards use formatVenueTypeTitle. */
export function formatCategoryBadge(category: string): { label: string; kind: "category" } {
  const key = category.trim().toLowerCase();
  const label =
    CATEGORY_BADGE_LABELS[key] ?? category.replaceAll("_", " ").toUpperCase();
  return { label, kind: "category" };
}

export function formatVenueTypeTitle(category: string): string {
  const key = category.trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
  if (VENUE_TYPE_TITLES[key]) {
    return VENUE_TYPE_TITLES[key];
  }
  return category
    .trim()
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

export function resolveDiscoverCity(venues: { city: string }[]): string {
  if (venues.length === 0) {
    return "Nearby";
  }
  const counts = new Map<string, number>();
  for (const venue of venues) {
    const city = venue.city.trim();
    if (!city) {
      continue;
    }
    counts.set(city, (counts.get(city) ?? 0) + 1);
  }
  let best = venues[0]?.city?.trim() || "Nearby";
  let bestCount = 0;
  for (const [city, count] of counts) {
    if (count > bestCount) {
      best = city;
      bestCount = count;
    }
  }
  return best;
}

/** City picker is not implemented — chevron must stay hidden. */
export function canChangeDiscoverCity(): boolean {
  return false;
}

/**
 * Preferred Discover distance labels (imperial).
 * Examples: 350 ft · 0.2 mi · 1.4 mi
 */
export function formatDiscoverDistance(distanceM: number | undefined): string | null {
  if (distanceM == null || Number.isNaN(distanceM) || distanceM < 0) {
    return null;
  }
  const feet = distanceM * 3.280839895;
  const miles = distanceM / 1609.344;
  if (miles < 0.1) {
    return `${Math.max(1, Math.round(feet))} ft`;
  }
  const rounded = miles < 10 ? miles.toFixed(1) : miles.toFixed(0);
  return `${rounded} mi`;
}

/** Legacy helper retained for older tests — prefer formatDiscoverDistance. */
export function formatDistanceLabel(distanceM: number | undefined): string | null {
  return formatDiscoverDistance(distanceM);
}

export function resolveOpenState(venue: VenueLike): OpenState | null {
  if (venue.is_open === true) {
    return { label: "Open", tone: "open" };
  }
  if (venue.is_open === false) {
    return { label: "Closed", tone: "closed" };
  }
  return null;
}

export function formatPrimaryMetaSegments(venue: VenueLike): MetaSegment[] {
  const segments: MetaSegment[] = [];
  const type = formatVenueTypeTitle(venue.category);
  const distance = formatDiscoverDistance(venue.distance_m);
  const open = resolveOpenState(venue);

  const push = (text: string, tone: MetaSegment["tone"]) => {
    if (segments.length > 0) {
      segments.push({ text: " • ", tone: "separator" });
    }
    segments.push({ text, tone });
  };

  push(type, "muted");
  if (distance) {
    push(distance, "muted");
  }
  if (open) {
    push(open.label, open.tone);
  }
  return segments;
}

export function formatPrimaryMetaLine(venue: VenueLike): string {
  return formatPrimaryMetaSegments(venue)
    .filter((s) => s.tone !== "separator")
    .map((s) => s.text)
    .join(" • ");
}

/**
 * Crowd / packed row — only when real API data exists.
 * Never invent a percentage from vibes, time, or category.
 */
export function formatCrowdRow(venue: VenueLike): CrowdRow | null {
  if (typeof venue.packed_percent === "number" && Number.isFinite(venue.packed_percent)) {
    const clamped = Math.min(100, Math.max(0, venue.packed_percent));
    const whole = Math.round(clamped);
    return { kind: "percent", text: `${whole}% Packed`, value: whole };
  }
  const label = venue.crowd_label?.trim();
  if (label) {
    return { kind: "label", text: label };
  }
  return null;
}

/** @deprecated Top badges removed from Discover cards. */
export function resolveStatusBadge(
  venue: VenueLike,
): { label: string; kind: "live" | "nearby" } | null {
  if (venue.experience_tags.includes("live_set")) {
    return { label: "LIVE SET", kind: "live" };
  }
  if (typeof venue.distance_m === "number" && venue.distance_m <= 250) {
    return { label: "NEARBY", kind: "nearby" };
  }
  return null;
}

export function formatLocationLine(venue: VenueLike): string {
  return venue.city;
}

/** @deprecated Prefer formatPrimaryMetaLine. */
export function formatCardMeta(venue: VenueLike): string | null {
  return formatDiscoverDistance(venue.distance_m);
}

export function venueAccessibilityLabel(venue: VenueLike): string {
  const parts = [venue.name, formatPrimaryMetaLine(venue)];
  const crowd = formatCrowdRow(venue);
  if (crowd) {
    parts.push(crowd.text);
  }
  return parts.filter(Boolean).join(", ");
}

/** Guardrails used by tests — Discover must never invent these. */
export function containsForbiddenDiscoverCopy(text: string): boolean {
  return /(london|mayfair|chelsea|aether lounge|vesper vault|min spend|vip member|exclusive|★★|premium member)/i.test(
    text,
  );
}

export function truncatesVenueNameSafe(name: string, maxChars = 48): string {
  const trimmed = name.trim();
  if (trimmed.length <= maxChars) {
    return trimmed;
  }
  return `${trimmed.slice(0, maxChars - 1)}…`;
}
