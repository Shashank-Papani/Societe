/** Coordinate projection helpers — no path-alias imports (Node-test friendly). */

export function projectVenuePins(
  venues: { id: string; latitude: number; longitude: number }[],
  width: number,
  height: number,
  padding = 28,
): { id: string; x: number; y: number }[] {
  if (venues.length === 0 || width <= 0 || height <= 0) {
    return [];
  }
  const lats = venues.map((v) => v.latitude);
  const lngs = venues.map((v) => v.longitude);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const latSpan = Math.max(maxLat - minLat, 0.0008);
  const lngSpan = Math.max(maxLng - minLng, 0.0008);
  const innerW = Math.max(width - padding * 2, 1);
  const innerH = Math.max(height - padding * 2, 1);

  return venues.map((venue) => ({
    id: venue.id,
    x: padding + ((venue.longitude - minLng) / lngSpan) * innerW,
    y: padding + ((maxLat - venue.latitude) / latSpan) * innerH,
  }));
}
