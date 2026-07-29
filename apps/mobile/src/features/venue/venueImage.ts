/**
 * Venue identity media vs Live Vibe media — kept strictly separate.
 *
 * IDENTITY (Discover / Presence / Venue Detail hero):
 *   1. approved owner-selected venue cover URL
 *   2. approved venue gallery image designated as primary
 *   3. approved stable venue gallery image
 *   4. explicit venue-name fallback
 *   5. normalized category fallback
 *   6. generic venue fallback
 *
 * Live Vibes are never identity media. Changing a venue cover requires an
 * explicit owner/admin cover selection — not the newest user post.
 */

export type VenueFallbackAssetKey =
  | "club"
  | "rooftop"
  | "sportsBar"
  | "bar2"
  | "lounge1"
  | "lounge2"
  | "generic";

export type VenueIdentityImageInputs = {
  /** Approved owner-selected cover URL from API (when available). */
  approvedCoverUrl?: string | null;
  /** @deprecated Prefer approvedCoverUrl — kept for call-site compatibility. */
  coverImageUrl?: string | null;
  /** Approved primary gallery image URL from API (when available). */
  primaryGalleryImageUrl?: string | null;
  /** Approved stable gallery image URL from API (when available). */
  approvedGalleryImageUrl?: string | null;
  /** @deprecated Prefer primary/approved gallery fields. */
  galleryImageUrl?: string | null;
  /** Venue category as returned by the API (not mutated). */
  category?: string | null;
  /** Stable venue id for deterministic lounge selection. */
  venueId?: string | null;
  /** Venue display name for explicit fallback mapping (not mutated). */
  venueName?: string | null;
};

/** @deprecated Use VenueIdentityImageInputs — Live Vibe fields are ignored. */
export type VenueImageInputs = VenueIdentityImageInputs & {
  liveVibeImageUrl?: string | null;
  allowLiveVibePreview?: boolean;
};

export type ResolvedVenueIdentityImage =
  | { kind: "remote"; uri: string; source: "cover" | "gallery" }
  | {
      kind: "fallback";
      source: "fallback";
      assetKey: VenueFallbackAssetKey;
    };

/** @deprecated Alias of ResolvedVenueIdentityImage (live_vibe source removed). */
export type ResolvedVenueImage = ResolvedVenueIdentityImage;

export type ResolvedLiveVibeMedia =
  | { kind: "remote"; uri: string; source: "media" | "thumbnail" }
  | { kind: "local"; uri: string }
  | { kind: "none" };

function isUsableUrl(value: string | null | undefined): value is string {
  if (!value) {
    return false;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }
  if (!(trimmed.startsWith("https://") || trimmed.startsWith("http://"))) {
    return false;
  }
  if (trimmed.includes(" ") || trimmed === "null" || trimmed === "undefined") {
    return false;
  }
  return true;
}

/** Normalize for mapping only — does not mutate the backend value. */
export function normalizeVenueCategory(category: string | null | undefined): string {
  if (category == null) {
    return "";
  }
  return category
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

/** Normalize venue names for explicit asset mapping only. */
export function normalizeVenueName(name: string | null | undefined): string {
  if (name == null) {
    return "";
  }
  return name
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Explicit venue-name fallbacks (checked before category).
 * Seed uses “Copper Mirage”; vision copy uses “Cooper Mirage” — both map to bar2.
 */
export function resolveExplicitVenueFallbackKey(
  venueName: string | null | undefined,
): VenueFallbackAssetKey | null {
  const normalized = normalizeVenueName(venueName);
  if (normalized === "cooper mirage" || normalized === "copper mirage") {
    return "bar2";
  }
  return null;
}

/**
 * Deterministic lounge asset choice. Same venueId → same lounge across
 * rerenders, restarts, Discover, and Venue Detail. No Math.random().
 */
export function selectLoungeFallback(
  venueId: string | null | undefined,
): "lounge1" | "lounge2" {
  const id = venueId?.trim();
  if (!id) {
    return "lounge1";
  }
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return hash % 2 === 0 ? "lounge1" : "lounge2";
}

export function resolveCategoryFallbackKey(
  category: string | null | undefined,
  venueId: string | null | undefined,
  venueName?: string | null,
): VenueFallbackAssetKey {
  const explicit = resolveExplicitVenueFallbackKey(venueName);
  if (explicit) {
    return explicit;
  }

  const normalized = normalizeVenueCategory(category);
  if (!normalized) {
    return "generic";
  }

  if (
    normalized === "club" ||
    normalized === "nightclub" ||
    normalized === "night_club" ||
    normalized === "dance_club"
  ) {
    return "club";
  }

  if (
    normalized === "rooftop" ||
    normalized === "rooftop_bar" ||
    normalized === "terrace"
  ) {
    return "rooftop";
  }

  if (
    normalized === "bar" ||
    normalized === "sports_bar" ||
    normalized === "sportsbar" ||
    normalized === "pub"
  ) {
    return "sportsBar";
  }

  if (normalized === "lounge" || normalized === "cocktail_lounge") {
    return selectLoungeFallback(venueId);
  }

  // live_music, warehouse, restaurant, event_space, unknown → generic
  return "generic";
}

/**
 * Stable venue identity image. Never returns user Live Vibe media.
 */
export function resolveVenueIdentityImage(
  inputs: VenueIdentityImageInputs,
): ResolvedVenueIdentityImage {
  const cover = inputs.approvedCoverUrl ?? inputs.coverImageUrl;
  if (isUsableUrl(cover)) {
    return { kind: "remote", uri: cover, source: "cover" };
  }

  const primaryGallery = inputs.primaryGalleryImageUrl ?? inputs.galleryImageUrl;
  if (isUsableUrl(primaryGallery)) {
    return { kind: "remote", uri: primaryGallery, source: "gallery" };
  }

  if (isUsableUrl(inputs.approvedGalleryImageUrl)) {
    return { kind: "remote", uri: inputs.approvedGalleryImageUrl, source: "gallery" };
  }

  return {
    kind: "fallback",
    source: "fallback",
    assetKey: resolveCategoryFallbackKey(
      inputs.category,
      inputs.venueId,
      inputs.venueName,
    ),
  };
}

/**
 * Compatibility wrapper — identity media only.
 * `liveVibeImageUrl` / `allowLiveVibePreview` are intentionally ignored.
 */
export function resolveVenueImage(inputs: VenueImageInputs): ResolvedVenueImage {
  return resolveVenueIdentityImage(inputs);
}

/** After a remote identity-media load failure, fall back to explicit/category asset. */
export function venueImageFailedFallback(
  inputs: Pick<VenueIdentityImageInputs, "category" | "venueId" | "venueName"> = {},
): ResolvedVenueIdentityImage {
  return {
    kind: "fallback",
    source: "fallback",
    assetKey: resolveCategoryFallbackKey(
      inputs.category,
      inputs.venueId,
      inputs.venueName,
    ),
  };
}

/**
 * Live Vibe media only — never used for venue identity/hero.
 *
 * Priority:
 * 1. approved media URL
 * 2. approved thumbnail URL
 * 3. local optimistic URI while pending
 * 4. none → caller renders noir failure
 */
export function resolveLiveVibeMedia(input: {
  mediaUrl?: string | null;
  thumbnailUrl?: string | null;
  optimisticLocalUri?: string | null;
  pending?: boolean;
}): ResolvedLiveVibeMedia {
  if (isUsableUrl(input.mediaUrl)) {
    return { kind: "remote", uri: input.mediaUrl, source: "media" };
  }
  if (isUsableUrl(input.thumbnailUrl)) {
    return { kind: "remote", uri: input.thumbnailUrl, source: "thumbnail" };
  }
  const local = input.optimisticLocalUri?.trim() ?? "";
  if (
    input.pending &&
    local &&
    (local.startsWith("file://") ||
      local.startsWith("ph://") ||
      local.startsWith("content://") ||
      local.startsWith("data:image/"))
  ) {
    return { kind: "local", uri: local };
  }
  return { kind: "none" };
}

export type LiveVibeLike = {
  media_type: string;
  published_at: string;
  variants: { url: string; variant_type?: string }[];
};

/** First approved feed image URL for Live Vibe sections (not venue identity). */
export function pickApprovedLiveVibeImage(items: LiveVibeLike[] | null | undefined): {
  url: string;
  thumbnailUrl: string | null;
  publishedAt: string;
} | null {
  if (!items?.length) {
    return null;
  }
  for (const item of items) {
    if (item.media_type !== "image") {
      continue;
    }
    let mediaUrl: string | null = null;
    let thumbnailUrl: string | null = null;
    for (const variant of item.variants) {
      if (!isUsableUrl(variant.url)) {
        continue;
      }
      const type = (variant.variant_type ?? "").trim().toLowerCase();
      if (/thumb/.test(type)) {
        thumbnailUrl = thumbnailUrl ?? variant.url;
        continue;
      }
      mediaUrl = mediaUrl ?? variant.url;
    }
    const url = mediaUrl ?? thumbnailUrl;
    if (url) {
      return { url, thumbnailUrl, publishedAt: item.published_at };
    }
  }
  return null;
}
