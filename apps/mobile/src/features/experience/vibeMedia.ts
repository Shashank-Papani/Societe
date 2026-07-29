/**
 * Live Vibe media source resolution — approved server URLs win over local previews.
 */

export const LIVE_VIBE_MEDIA_ASPECT_RATIO = 4 / 5;

export type VibeMediaVariant = {
  variant_type: string;
  mime_type: string;
  url: string;
  width?: number | null;
  height?: number | null;
  duration_ms?: number | null;
  expires_at: string;
};

export type ResolvedVibeMedia =
  | { kind: "remote"; uri: string; variantType: string }
  | { kind: "local"; uri: string }
  | { kind: "none" };

const VARIANT_PRIORITY = [
  "image_1080",
  "image_720",
  "feed",
  "original",
  "full",
  "image",
  "poster",
  "thumbnail",
  "thumb",
] as const;

function isHttpUrl(url: string): boolean {
  const trimmed = url.trim();
  return trimmed.startsWith("https://") || trimmed.startsWith("http://");
}

function isLocalUri(uri: string): boolean {
  const trimmed = uri.trim();
  return (
    trimmed.startsWith("file://") ||
    trimmed.startsWith("ph://") ||
    trimmed.startsWith("assets-library://") ||
    trimmed.startsWith("content://") ||
    trimmed.startsWith("data:image/")
  );
}

function pickPreferredVariant(variants: VibeMediaVariant[]): VibeMediaVariant | null {
  const usable = variants.filter((variant) => isHttpUrl(variant.url));
  if (usable.length === 0) {
    return null;
  }
  for (const preferred of VARIANT_PRIORITY) {
    const match = usable.find(
      (variant) => variant.variant_type.trim().toLowerCase() === preferred,
    );
    if (match) {
      return match;
    }
  }
  // Prefer non-thumbnail when type is unknown.
  const nonThumb = usable.find(
    (variant) => !/thumb/i.test(variant.variant_type),
  );
  return nonThumb ?? usable[0] ?? null;
}

/**
 * Priority:
 * 1. approved signed/public media URL from the server
 * 2. approved thumbnail when full media is unavailable
 * 3. local optimistic URI while still pending
 * 4. none → caller renders noir failure/empty placeholder
 */
export function resolveVibeMediaSource(input: {
  variants: VibeMediaVariant[];
  localUri?: string | null;
  pending?: boolean;
}): ResolvedVibeMedia {
  const remote = pickPreferredVariant(input.variants);
  if (remote) {
    return { kind: "remote", uri: remote.url.trim(), variantType: remote.variant_type };
  }
  if (input.pending && input.localUri && isLocalUri(input.localUri)) {
    return { kind: "local", uri: input.localUri.trim() };
  }
  return { kind: "none" };
}

export type FeedListItem =
  | { kind: "server"; id: string; serverId: string; item: import("./api").VibeFeedItem }
  | {
      kind: "optimistic";
      id: string;
      clientRequestId: string;
      liveVibeId?: string | null;
      localUri: string;
      caption: string | null;
      vibeTags: string[];
      authorLabel: string;
      publishedAt: string;
      expiresAt: string;
      status: "uploading" | "processing" | "under_review";
    };

/**
 * Merge optimistic rows with server feed items. Server wins when ids match.
 */
export function reconcileVibeFeed(input: {
  serverItems: import("./api").VibeFeedItem[];
  optimistic: FeedListItem[];
}): FeedListItem[] {
  const serverIds = new Set(input.serverItems.map((item) => item.id));
  const serverRows: FeedListItem[] = input.serverItems.map((item) => ({
    kind: "server",
    id: item.id,
    serverId: item.id,
    item,
  }));

  const pendingOptimistic = input.optimistic.filter((row) => {
    if (row.kind !== "optimistic") {
      return false;
    }
    if (row.liveVibeId && serverIds.has(row.liveVibeId)) {
      return false;
    }
    return true;
  });

  return [...pendingOptimistic, ...serverRows];
}

export function composerShouldShow(phase: string): boolean {
  return ![
    "idle",
    "cancelled",
    "published",
  ].includes(phase);
}
