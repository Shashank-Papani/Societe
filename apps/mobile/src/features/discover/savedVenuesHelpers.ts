/** Pure saved-venue helpers — unit-testable without FileSystem. */

export function toggleSavedVenueId(current: string[], venueId: string): string[] {
  if (current.includes(venueId)) {
    return current.filter((id) => id !== venueId);
  }
  return [...current, venueId];
}

export function isVenueSaved(current: string[], venueId: string): boolean {
  return current.includes(venueId);
}
