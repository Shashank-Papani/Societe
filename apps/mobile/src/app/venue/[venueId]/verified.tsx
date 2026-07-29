import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";

import { useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";
import { fetchVenueDetail } from "@/features/discover/api";
import { fetchPresenceMe } from "@/features/presence/api";
import { PresenceVerifiedScreen } from "@/features/presence/PresenceVerifiedScreen";
import { isVerifiedAtVenue } from "@/features/venue/venuePresentation";
import { colors } from "@/theme";

export default function VenuePresenceVerifiedRoute() {
  const auth = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ venueId: string; verifiedAt?: string }>();
  const venueId = String(params.venueId ?? "");
  const verifiedAt = typeof params.verifiedAt === "string" ? params.verifiedAt : null;

  const detailQuery = useQuery({
    queryKey: ["venue", venueId],
    queryFn: () => fetchVenueDetail(venueId),
    enabled: Boolean(venueId) && auth.status === "authenticated",
  });

  const presenceQuery = useQuery({
    queryKey: ["presence", "me"],
    queryFn: fetchPresenceMe,
    enabled: auth.status === "authenticated",
  });

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
  });

  const presence = presenceQuery.data;
  const verified = isVerifiedAtVenue(presence, venueId);
  const venueName =
    detailQuery.data?.name ??
    (presence?.venue?.id === venueId ? presence.venue.name : "Venue");
  const ready =
    auth.status !== "initializing" &&
    !presenceQuery.isLoading &&
    !detailQuery.isLoading;

  useEffect(() => {
    if (ready && !verified && venueId) {
      router.replace(`/venue/${venueId}`);
    }
  }, [ready, verified, venueId, router]);

  if (!ready) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={colors.lime} />
      </View>
    );
  }

  if (!verified) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={colors.lime} />
      </View>
    );
  }

  return (
    <PresenceVerifiedScreen
      venueName={venueName}
      venueId={venueId}
      verifiedAtIso={verifiedAt}
      expiresAtIso={presence?.lease_expires_at}
      verificationLevel={presence?.verification_level}
      ghostMode={
        meQuery.data?.privacy.ghost_mode ||
        meQuery.data?.privacy.effective.ghost_mode_overrides
      }
      discoverableInVenue={meQuery.data?.privacy.effective.discoverable_in_venue}
      socialFeaturesEnabled={presence?.social_features_enabled}
      timeZone={detailQuery.data?.timezone}
      onSeeWhosHere={() => router.push("/(tabs)/connect")}
      onBackToVenue={() => router.replace(`/venue/${venueId}`)}
      onViewLiveVibes={() => router.push("/(tabs)/experience")}
    />
  );
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: "center",
    justifyContent: "center",
  },
});
