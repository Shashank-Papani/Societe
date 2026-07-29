/**
 * Pure Venue Detail / Presence Verified presentation helpers.
 */

export type VenueHoursRow = {
  weekday: number;
  opens_local: string;
  closes_local: string;
  closes_next_day: boolean;
};

export type VenueDetailLike = {
  id: string;
  name: string;
  category: string;
  status: string;
  description?: string | null;
  street_address?: string | null;
  city: string;
  region?: string | null;
  music_tags: string[];
  experience_tags: string[];
  hours: VenueHoursRow[];
  price_band?: number | null;
};

export type PresenceLike = {
  state: string;
  venue: { id: string; name: string } | null;
  verification_level: string | null;
  lease_expires_at: string | null;
  social_features_enabled: boolean;
  reasons: string[];
};

const CATEGORY_LABELS: Record<string, string> = {
  nightclub: "CLUB",
  bar: "BAR",
  lounge: "LOUNGE",
  rooftop: "ROOFTOP",
  live_music: "LIVE MUSIC",
  warehouse: "WAREHOUSE",
};

export function formatVenueCategory(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replaceAll("_", " ").toUpperCase();
}

export function formatVenueLocation(venue: Pick<VenueDetailLike, "city" | "region" | "street_address">): string {
  const parts = [venue.city];
  if (venue.region) {
    parts.push(venue.region);
  }
  return parts.join(", ");
}

/** Derive open copy from real hours when possible; never invent closing times. */
export function formatOpenState(
  venue: Pick<VenueDetailLike, "status" | "hours">,
  now: Date = new Date(),
): string | null {
  if (venue.status && venue.status !== "active") {
    return "UNAVAILABLE";
  }
  if (!venue.hours.length) {
    return null;
  }
  // API weekday: 0=Mon … 6=Sun (matches current Venue Detail screen).
  const jsDay = now.getDay(); // 0=Sun
  const apiWeekday = jsDay === 0 ? 6 : jsDay - 1;
  const today = venue.hours.find((row) => row.weekday === apiWeekday);
  if (!today) {
    return null;
  }
  return `OPEN UNTIL ${today.closes_local}`;
}

export function isVerifiedAtVenue(
  presence: PresenceLike | null | undefined,
  venueId: string,
  nowMs: number = Date.now(),
): boolean {
  if (!presence || !presence.venue) {
    return false;
  }
  // Rechecking keeps venue presence temporarily active (hysteresis).
  if (presence.state !== "verified" && presence.state !== "rechecking") {
    return false;
  }
  if (presence.venue.id !== venueId) {
    return false;
  }
  if (presence.lease_expires_at && presence.state === "verified") {
    const expires = Date.parse(presence.lease_expires_at);
    if (Number.isFinite(expires) && expires <= nowMs) {
      return false;
    }
  }
  return true;
}

export function formatVisibilityLabel(params: {
  ghostMode?: boolean;
  discoverableInVenue?: boolean;
  socialFeaturesEnabled?: boolean;
}): string {
  if (params.ghostMode) {
    return "Ghost Mode";
  }
  if (params.discoverableInVenue === false) {
    return "Hidden";
  }
  if (params.socialFeaturesEnabled === false) {
    return "Limited";
  }
  if (params.discoverableInVenue) {
    return "Discoverable";
  }
  return "According to privacy settings";
}

export function formatMethodLabel(verificationLevel: string | null | undefined): string {
  if (!verificationLevel) {
    return "Location verification";
  }
  const normalized = verificationLevel.replaceAll("_", " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function formatClock(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
      timeZone: timeZone || undefined,
    }).format(date);
  } catch {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
}

export function containsForbiddenVenueCopy(text: string): boolean {
  return /(min spend|vip bottle|reserve vip|obsidian|emerald grand|apple wallet|pass id|★★|£\d|table reservation)/i.test(
    text,
  );
}

export function primaryVenueAction(verified: boolean): {
  label: string;
  accessibilityLabel: string;
  kind: "verify" | "see_whos_here";
} {
  if (verified) {
    return {
      label: "SEE WHO’S HERE",
      accessibilityLabel: "See who’s here",
      kind: "see_whos_here",
    };
  }
  return {
    label: "VERIFY PRESENCE",
    accessibilityLabel: "Verify presence",
    kind: "verify",
  };
}

export function formatRelativeAge(iso: string | null | undefined, nowMs: number = Date.now()): string | null {
  if (!iso) {
    return null;
  }
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) {
    return null;
  }
  const deltaMs = Math.max(0, nowMs - then);
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 1) {
    return "Just now";
  }
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function isVenueMissingError(error: unknown): boolean {
  if (!error || typeof error !== "object") {
    return false;
  }
  const status = "status" in error ? Number((error as { status?: number }).status) : NaN;
  const code = "code" in error ? String((error as { code?: string }).code ?? "") : "";
  return status === 404 || /NOT_FOUND|VENUE_NOT_FOUND/i.test(code);
}

export function parseDistanceParam(value: string | string[] | undefined): number | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw == null || raw === "") {
    return undefined;
  }
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}
