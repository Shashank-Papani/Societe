import { useLocalSearchParams } from "expo-router";

import { VenueDetailScreen } from "@/features/venue/VenueDetailScreen";
import { parseDistanceParam } from "@/features/venue/venuePresentation";

export default function VenueDetailRoute() {
  const params = useLocalSearchParams<{ venueId: string; distance_m?: string }>();
  const venueId = String(params.venueId ?? "");
  const distanceM = parseDistanceParam(params.distance_m);

  return <VenueDetailScreen venueId={venueId} distanceM={distanceM} />;
}
