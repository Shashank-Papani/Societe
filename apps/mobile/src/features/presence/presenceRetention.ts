/**
 * Presence retention presentation and local helpers.
 * Never trust client distance for authorization — server decides.
 */

import type { PresenceSnapshot } from "@/features/presence/api";

export type PresencePresentationState =
  | "inactive"
  | "active"
  | "rechecking"
  | "grace"
  | "expired"
  | "revoked";

export function haversineMeters(
  a: { latitude: number; longitude: number },
  b: { latitude: number; longitude: number },
): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const earth = 6_371_000;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * earth * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function resolvePresentationState(
  presence: PresenceSnapshot | null | undefined,
): PresencePresentationState {
  if (!presence) {
    return "inactive";
  }
  switch (presence.state) {
    case "verified":
      return presence.outside_confirmation_pending ? "rechecking" : "active";
    case "rechecking":
      return "rechecking";
    case "degraded":
      return "grace";
    case "exited":
      return presence.decision === "revoked" ||
        presence.reasons.some((r) => r.includes("left_retention"))
        ? "revoked"
        : "expired";
    case "outside":
    case "refresh_required":
      return "inactive";
    default:
      return "inactive";
  }
}

export function presenceStatusLabel(state: PresencePresentationState): string {
  switch (state) {
    case "active":
      return "Presence Verified";
    case "rechecking":
      return "Rechecking your location…";
    case "grace":
      return "Keeping your presence active";
    case "expired":
      return "Presence expired";
    case "revoked":
      return "You’ve left the venue area";
    default:
      return "Verify Presence";
  }
}

export function presenceStatusSupportingCopy(
  state: PresencePresentationState,
): string | null {
  if (state === "grace") {
    return "Open Société to refresh your location.";
  }
  if (state === "rechecking") {
    return "Confirming you are still nearby…";
  }
  return null;
}

/** Social eligibility follows server state; rechecking remains temporarily active. */
export function isSociallyPresent(
  presence: PresenceSnapshot | null | undefined,
): boolean {
  if (!presence) {
    return false;
  }
  return (
    presence.state === "verified" ||
    presence.state === "rechecking" ||
    (presence.social_features_enabled && presence.state === "degraded")
  );
}

export function isActivelyPresentAtVenue(
  presence: PresenceSnapshot | null | undefined,
  venueId: string,
  nowMs: number = Date.now(),
): boolean {
  if (!presence?.venue || presence.venue.id !== venueId) {
    return false;
  }
  if (presence.state !== "verified" && presence.state !== "rechecking") {
    return false;
  }
  if (presence.lease_expires_at) {
    const expires = Date.parse(presence.lease_expires_at);
    // During rechecking, lease_expires_at is still the verified window.
    if (Number.isFinite(expires) && expires <= nowMs && presence.state === "verified") {
      // Grace may still apply via degraded; verified-past-lease is not active.
      return false;
    }
  }
  return true;
}

/**
 * Offset a coordinate by approximate meters (north+, east+).
 * Development fixture helpers only.
 */
export function offsetLatLng(
  origin: { latitude: number; longitude: number },
  metersNorth: number,
  metersEast: number,
): { latitude: number; longitude: number } {
  const lat = origin.latitude + metersNorth / 111_320;
  const lng =
    origin.longitude + metersEast / (111_320 * Math.cos((origin.latitude * Math.PI) / 180));
  return { latitude: lat, longitude: lng };
}

export function shouldStartRetention(presence: PresenceSnapshot | null): boolean {
  return Boolean(
    presence &&
      presence.venue?.id &&
      (presence.state === "verified" ||
        presence.state === "rechecking" ||
        presence.state === "degraded"),
  );
}

export function shouldTriggerMovementHeartbeat(input: {
  movedMeters: number;
  secondsSinceLastSubmit: number;
  accuracyMeters: number;
  maxAccuracyMeters?: number;
  movementMeters?: number;
  throttleSeconds?: number;
}): boolean {
  const maxAccuracy = input.maxAccuracyMeters ?? 50;
  const movement = input.movementMeters ?? 30;
  const throttle = input.throttleSeconds ?? 45;
  if (input.accuracyMeters > maxAccuracy) {
    return false;
  }
  return input.movedMeters >= movement && input.secondsSinceLastSubmit >= throttle;
}
