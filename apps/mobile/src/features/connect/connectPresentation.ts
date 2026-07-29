/**
 * Connect / Calling Card presentation helpers (friendly copy only).
 * Does not change queue or API behavior.
 */

export type NearbyPersonLike = {
  user_id: string;
  handle: string;
  display_name: string;
};

export type ConnectUiStateLike =
  | "queued"
  | "sending"
  | "server_pending"
  | "delivered"
  | "accepted"
  | "declined"
  | "expired"
  | "cancelled"
  | "failed_retryable"
  | "failed_permanent";

export function nearbyPersonAccessibilityLabel(person: NearbyPersonLike): string {
  return `${person.display_name}, @${person.handle}`;
}

/** Production-facing Calling Card / queue labels — never expose operation names. */
export function friendlyConnectStateLabel(state: ConnectUiStateLike | string): string {
  switch (state) {
    case "queued":
      return "Waiting for connection";
    case "sending":
      return "Sending…";
    case "server_pending":
      return "Pending";
    case "delivered":
      return "Sent";
    case "accepted":
      return "Connected";
    case "declined":
      return "Declined";
    case "expired":
      return "Expired";
    case "cancelled":
      return "Cancelled";
    case "failed_retryable":
      return "Will retry automatically";
    case "failed_permanent":
      return "Couldn’t send";
    default:
      return "Pending";
  }
}

export function mapCardStatusToUiState(status: string): ConnectUiStateLike {
  switch (status) {
    case "pending":
      return "delivered";
    case "accepted":
      return "accepted";
    case "declined":
      return "declined";
    case "expired":
      return "expired";
    case "cancelled":
      return "cancelled";
    case "blocked":
      return "failed_permanent";
    default:
      return "server_pending";
  }
}

export function friendlyCardStatusLabel(status: string): string {
  return friendlyConnectStateLabel(mapCardStatusToUiState(status));
}

export function primaryCardActionLabel(status: string, kind: "nearby" | "outgoing"): string {
  if (kind === "nearby") {
    return "Send Calling Card";
  }
  const ui = mapCardStatusToUiState(status);
  if (ui === "accepted") {
    return "Message";
  }
  if (ui === "failed_retryable" || ui === "failed_permanent") {
    return "Try Again";
  }
  if (ui === "delivered" || ui === "server_pending") {
    return "Pending";
  }
  return friendlyConnectStateLabel(ui);
}

export function formatConnectionAvailable(
  expiresAt: string | null | undefined,
  nowMs: number = Date.now(),
): string | null {
  if (!expiresAt) {
    return null;
  }
  const end = Date.parse(expiresAt);
  if (Number.isNaN(end)) {
    return null;
  }
  const remainingMs = end - nowMs;
  if (remainingMs <= 0) {
    return null;
  }
  const minutes = Math.max(1, Math.round(remainingMs / 60_000));
  if (minutes >= 120) {
    const hours = Math.round(minutes / 60);
    return `Connection available for ${hours} hours`;
  }
  return `Connection available for ${minutes} minute${minutes === 1 ? "" : "s"}`;
}

export function formatRelativeTime(
  iso: string | null | undefined,
  nowMs: number = Date.now(),
): string | null {
  if (!iso) {
    return null;
  }
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) {
    return null;
  }
  const delta = Math.max(0, nowMs - then);
  const minutes = Math.floor(delta / 60_000);
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

export function presenceContextLabel(params: {
  venueName: string | null;
  verified: boolean;
  ghostOn: boolean;
}): string | null {
  if (params.ghostOn) {
    return "Ghost Mode on";
  }
  if (params.verified && params.venueName) {
    return `${params.venueName} · Presence verified`;
  }
  if (params.venueName) {
    return params.venueName;
  }
  if (!params.verified) {
    return "Not verified at a venue";
  }
  return null;
}

export function containsForbiddenConnectCopy(text: string): boolean {
  return /(server-authoritative|Presence gate|social eligible|calling_card\.(create|respond|cancel)|Failed · will retry|NETWORK|reconciliation)/i.test(
    text,
  );
}

export function avatarInitials(displayName: string, handle?: string | null): string {
  const source = displayName.trim() || handle?.trim() || "?";
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0]![0]!}${parts[1]![0]!}`.toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
}

/** Deterministic soft accent for placeholder avatars (noir-safe, not blue). */
export function avatarAccent(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  const accents = ["#1F3D2C", "#2A3320", "#243828", "#31401F", "#1A2E24"];
  return accents[hash % accents.length]!;
}
