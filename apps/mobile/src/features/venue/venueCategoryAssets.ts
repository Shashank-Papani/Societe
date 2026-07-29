/**
 * Static React Native asset map for venue category fallbacks.
 * Paths must be literal `require(...)` calls — never built from strings.
 */

import type {
  ResolvedVenueIdentityImage,
  VenueFallbackAssetKey,
  VenueIdentityImageInputs,
} from "@/features/venue/venueImage";
import {
  resolveVenueIdentityImage,
  venueImageFailedFallback,
} from "@/features/venue/venueImage";

/** @deprecated Prefer ResolvedVenueIdentityImage. */
export type ResolvedVenueImage = ResolvedVenueIdentityImage;
/** @deprecated Prefer VenueIdentityImageInputs. */
export type VenueImageInputs = VenueIdentityImageInputs;

export const VENUE_CATEGORY_IMAGES = {
  club: require("../../../assets/images/venue-categories/club.jpg"),
  rooftop: require("../../../assets/images/venue-categories/rooftop.jpg"),
  sportsBar: require("../../../assets/images/venue-categories/sports-bar.jpg"),
  bar2: require("../../../assets/images/venue-categories/bar2.jpg"),
  lounge1: require("../../../assets/images/venue-categories/lounge-1.jpg"),
  lounge2: require("../../../assets/images/venue-categories/lounge-2.jpg"),
  generic: require("../../../assets/images/venue-fallback.png"),
} as const;

export type VenueLocalImageSource =
  (typeof VENUE_CATEGORY_IMAGES)[VenueFallbackAssetKey];

export type VenueDisplayImageSource =
  | VenueLocalImageSource
  | { uri: string };

export function sourceForFallbackAssetKey(
  assetKey: VenueFallbackAssetKey,
): VenueLocalImageSource {
  return VENUE_CATEGORY_IMAGES[assetKey];
}

export function sourceForResolvedVenueImage(
  resolved: ResolvedVenueIdentityImage,
): VenueDisplayImageSource {
  if (resolved.kind === "remote") {
    return { uri: resolved.uri };
  }
  return sourceForFallbackAssetKey(resolved.assetKey);
}

/**
 * Display source for expo-image: use remote until it fails, then the venue’s
 * category (or generic) fallback. Never substitutes a Live Vibe.
 */
export function displayVenueImageSource(
  resolved: ResolvedVenueIdentityImage,
  failedRemoteUri: string | null,
  fallbackInputs: Pick<VenueIdentityImageInputs, "category" | "venueId" | "venueName">,
): VenueDisplayImageSource {
  if (resolved.kind === "remote" && failedRemoteUri !== resolved.uri) {
    return { uri: resolved.uri };
  }
  if (resolved.kind === "fallback") {
    return sourceForFallbackAssetKey(resolved.assetKey);
  }
  return sourceForResolvedVenueImage(venueImageFailedFallback(fallbackInputs));
}

/** Identity-media display helper for Discover / Presence / Venue Detail hero. */
export function resolveVenueDisplaySource(
  inputs: VenueIdentityImageInputs,
  failedRemoteUri: string | null = null,
): VenueDisplayImageSource {
  return displayVenueImageSource(resolveVenueIdentityImage(inputs), failedRemoteUri, {
    category: inputs.category,
    venueId: inputs.venueId,
    venueName: inputs.venueName,
  });
}
