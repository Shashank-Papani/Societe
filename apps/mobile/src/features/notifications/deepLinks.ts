/**
 * Strict parser for Phase 9A internal notification deep links.
 * Never pass raw deep_link strings into navigation.
 */

export type ParsedDeepLink =
  | { kind: "conversation"; conversationId: string }
  | { kind: "calling_card"; callingCardId: string }
  | { kind: "story"; storyId: string }
  | { kind: "experience" }
  | { kind: "venue_claim"; claimId: string }
  | { kind: "organization_invitation"; invitationId: string };

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const BLOCKED_SCHEMES = ["http:", "https:", "javascript:", "file:", "data:", "blob:"];

function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

/**
 * Parse a backend deep_link. Returns null when unsupported or unsafe.
 */
export function parseNotificationDeepLink(raw: string | null | undefined): ParsedDeepLink | null {
  if (raw == null) {
    return null;
  }
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }
  const lower = trimmed.toLowerCase();
  for (const scheme of BLOCKED_SCHEMES) {
    if (lower.startsWith(scheme)) {
      return null;
    }
  }
  if (!lower.startsWith("societe://")) {
    return null;
  }
  // Reject nested schemes / executable query payloads.
  if (trimmed.includes("?") || trimmed.includes("#")) {
    return null;
  }
  const rest = trimmed.slice("societe://".length);
  if (!rest || rest.includes("://")) {
    return null;
  }

  if (rest === "experience" || rest.startsWith("experience/")) {
    return { kind: "experience" };
  }

  const slash = rest.indexOf("/");
  if (slash <= 0) {
    return null;
  }
  const route = rest.slice(0, slash);
  const id = rest.slice(slash + 1);
  if (!id || id.includes("/")) {
    return null;
  }

  switch (route) {
    case "conversation":
      return isUuid(id) ? { kind: "conversation", conversationId: id } : null;
    case "calling-card":
      return isUuid(id) ? { kind: "calling_card", callingCardId: id } : null;
    case "story":
      return isUuid(id) ? { kind: "story", storyId: id } : null;
    case "venue-claim":
      return isUuid(id) ? { kind: "venue_claim", claimId: id } : null;
    case "organization-invitation":
      return isUuid(id) ? { kind: "organization_invitation", invitationId: id } : null;
    default:
      return null;
  }
}

/** Map a parsed link to an expo-router path (no execution). */
export function deepLinkToHref(link: ParsedDeepLink): string {
  switch (link.kind) {
    case "conversation":
      return `/messages/${link.conversationId}`;
    case "calling_card":
      return "/(tabs)/connect";
    case "story":
    case "experience":
      return "/(tabs)/experience";
    case "venue_claim":
      return "/notifications/info?kind=venue_claim";
    case "organization_invitation":
      return "/notifications/info?kind=organization_invitation";
    default: {
      const _exhaustive: never = link;
      return _exhaustive;
    }
  }
}
