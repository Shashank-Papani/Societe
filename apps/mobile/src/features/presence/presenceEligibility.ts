/**
 * Presence eligibility presentation — maps server reasons to UI copy.
 * Security decisions remain server-authoritative.
 */

/** Matches services/api max_evidence_age_seconds. */
export const PRESENCE_LOCATION_MAX_AGE_MS = 15_000;

export type PresenceEligibilityReason =
  | "eligible"
  | "already_verified"
  | "outside"
  | "stale_evidence"
  | "observed_at_in_future"
  | "accuracy_exceeds_venue_maximum"
  | "venue_inactive"
  | "venue_not_found"
  | "location_permission_denied"
  | "location_unavailable"
  | "location_stale"
  | "network"
  | "unknown"
  | "loading";

export type PresenceEligibilityView = {
  venueId: string;
  eligible: boolean;
  reason: PresenceEligibilityReason;
  distanceMeters: number | null;
  allowedRadiusMeters: number | null;
  locationAccuracyMeters: number | null;
  observedAt: string | null;
  userLatitude: number | null;
  userLongitude: number | null;
};

/**
 * Presence card distance. Avoids noisy foot precision from simulator GPS.
 *
 * < 30.48 m → `< 0.1 mi`
 * else miles to one decimal under 10 mi, integer at 10+ mi
 */
export function formatPresenceDistance(distanceMeters: number | null | undefined): string | null {
  if (distanceMeters == null || !Number.isFinite(distanceMeters) || distanceMeters < 0) {
    return null;
  }
  if (distanceMeters < 30.48) {
    return "< 0.1 mi";
  }
  const miles = distanceMeters / 1609.344;
  if (miles < 10) {
    return `${miles.toFixed(1)} mi`;
  }
  return `${Math.round(miles)} mi`;
}

export function mapEligibilityReasonToButtonLabel(
  reason: PresenceEligibilityReason,
  options?: { verifying?: boolean },
): string {
  if (options?.verifying) {
    return "Verifying…";
  }
  switch (reason) {
    case "loading":
      return "Checking location…";
    case "eligible":
      return "Verify Presence";
    case "already_verified":
      return "Presence Verified";
    case "outside":
      return "Not close enough";
    case "location_permission_denied":
      return "Enable location";
    case "location_unavailable":
      return "Location unavailable";
    case "location_stale":
    case "stale_evidence":
    case "observed_at_in_future":
      return "Refresh location";
    case "accuracy_exceeds_venue_maximum":
      return "Improve location accuracy";
    case "venue_inactive":
    case "venue_not_found":
      return "Venue unavailable";
    case "network":
    case "unknown":
      return "Try again";
    default:
      return "Try again";
  }
}

export function normalizeEligibilityReason(reason: string | null | undefined): PresenceEligibilityReason {
  if (!reason) {
    return "unknown";
  }
  const raw = reason.trim().toLowerCase();
  if (raw === "eligible") {
    return "eligible";
  }
  if (raw === "already_verified") {
    return "already_verified";
  }
  if (
    raw === "outside" ||
    raw.includes("outside") ||
    raw.includes("too_far") ||
    raw.includes("polygon")
  ) {
    return "outside";
  }
  if (raw === "stale_evidence" || raw === "location_stale") {
    return "stale_evidence";
  }
  if (raw === "observed_at_in_future") {
    return "observed_at_in_future";
  }
  if (raw.includes("accuracy")) {
    return "accuracy_exceeds_venue_maximum";
  }
  if (raw === "venue_inactive") {
    return "venue_inactive";
  }
  if (raw === "venue_not_found") {
    return "venue_not_found";
  }
  if (raw.includes("permission")) {
    return "location_permission_denied";
  }
  if (raw.includes("unavailable")) {
    return "location_unavailable";
  }
  if (raw.includes("network")) {
    return "network";
  }
  return "unknown";
}

export function isLocationSampleFresh(
  observedAtIso: string,
  nowMs: number = Date.now(),
  maxAgeMs: number = PRESENCE_LOCATION_MAX_AGE_MS,
): boolean {
  const observed = Date.parse(observedAtIso);
  if (!Number.isFinite(observed)) {
    return false;
  }
  return nowMs - observed <= maxAgeMs;
}

/** ~30 m south of Société Neon House seed centroid — development testing only. */
export const DEV_PRESENCE_TEST_LOCATION = {
  label: "dev-fixture · Neon House ~30m",
  latitude: 34.09523,
  longitude: -118.344,
  horizontal_accuracy_m: 8,
} as const;

export function formatPresenceMetaWithDistance(input: {
  category: string;
  distanceMeters?: number | null;
  distancePending?: boolean;
  hereNowCount?: number | null;
  formatVenueType: (category: string) => string;
}): string {
  const parts = [input.formatVenueType(input.category)];
  if (input.distancePending) {
    parts.push("Checking distance…");
  } else {
    const distance = formatPresenceDistance(input.distanceMeters);
    if (distance) {
      parts.push(distance);
    }
  }
  if (typeof input.hereNowCount === "number" && Number.isFinite(input.hereNowCount)) {
    parts.push(`${Math.max(0, Math.round(input.hereNowCount))} here now`);
  }
  return parts.join(" • ");
}
