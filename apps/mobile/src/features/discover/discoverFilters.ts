/**
 * Discover category filters — client presentation over real venue.category values.
 */

export type VenueCategoryValue =
  | "nightclub"
  | "bar"
  | "lounge"
  | "rooftop"
  | "live_music"
  | "warehouse";

export type DiscoverFilterKey =
  | "all"
  | "nightclub"
  | "lounge"
  | "rooftop"
  | "bar";

export type DiscoverFilter = {
  key: DiscoverFilterKey;
  label: string;
  /** Empty means no server category constraint (ALL). */
  categories: VenueCategoryValue[];
};

export const DISCOVER_FILTERS: readonly DiscoverFilter[] = [
  { key: "all", label: "All", categories: [] },
  { key: "nightclub", label: "Clubs", categories: ["nightclub"] },
  { key: "lounge", label: "Lounges", categories: ["lounge"] },
  { key: "rooftop", label: "Rooftops", categories: ["rooftop"] },
  { key: "bar", label: "Bars", categories: ["bar"] },
] as const;

export function filterByKey(key: DiscoverFilterKey): DiscoverFilter {
  return DISCOVER_FILTERS.find((item) => item.key === key) ?? DISCOVER_FILTERS[0];
}

export function categoriesForFilter(key: DiscoverFilterKey): string[] {
  return [...filterByKey(key).categories];
}

export function venueMatchesFilter(
  venueCategory: string,
  key: DiscoverFilterKey,
): boolean {
  if (key === "all") {
    return true;
  }
  return filterByKey(key).categories.includes(venueCategory as VenueCategoryValue);
}

export function filterVenues<T extends { category: string }>(
  venues: T[],
  key: DiscoverFilterKey,
): T[] {
  return venues.filter((venue) => venueMatchesFilter(venue.category, key));
}
