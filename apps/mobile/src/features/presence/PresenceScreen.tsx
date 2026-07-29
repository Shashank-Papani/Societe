import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/auth/AuthProvider";
import {
  TabScreenHeader,
  TAB_SCREEN_HORIZONTAL_PADDING,
} from "@/components/TabScreenHeader";
import { fetchDiscoverableUsers } from "@/features/connect/api";
import { fetchMapVenues } from "@/features/discover/api";
import { resolveDiscoverCity } from "@/features/discover/discoverPresentation";
import { PresenceLiveMap } from "@/features/presence/PresenceLiveMap";
import { fetchPresenceMe } from "@/features/presence/api";
import {
  PRESENCE_LOCATION_TO_STORIES_GAP,
  PRESENCE_MAP_HEIGHT,
  PRESENCE_STORY_IMAGE,
  PRESENCE_STORY_ITEM_WIDTH,
  PRESENCE_STORY_RING,
  PRESENCE_SURFACE,
} from "@/features/presence/presencePresentation";
import {
  presenceStatusLabel,
  presenceStatusSupportingCopy,
  resolvePresentationState,
} from "@/features/presence/presenceRetention";
import { usePresenceRetention } from "@/features/presence/PresenceRetentionProvider";
import { usePresenceEligibility } from "@/features/presence/usePresenceEligibility";
import {
  friendlyVerifyError,
  useVerifyPresence,
} from "@/features/presence/useVerifyPresence";
import { isVerifiedAtVenue } from "@/features/venue/venuePresentation";
import {
  applyDevVenueFixture,
  setDevLocationOverride,
} from "@/location/LocationProvider";
import { tabScreenBottomPadding } from "@/navigation/tabBar";
import { fontFamilies } from "@/theme";

const DEFAULT_CENTER = { latitude: 34.0955, longitude: -118.344 };
const DEFAULT_RADIUS_M = 8000;

function PresenceSkeleton() {
  return (
    <View style={styles.skeletonRoot} testID="presence-skeleton">
      <View style={styles.skeletonTitle} />
      <View style={styles.skeletonCity} />
      <View style={[styles.skeletonStories, { marginTop: PRESENCE_LOCATION_TO_STORIES_GAP }]}>
        {[0, 1, 2, 3, 4].map((key) => (
          <View key={key} style={styles.skeletonStory}>
            <View style={styles.skeletonRing} />
            <View style={styles.skeletonStoryName} />
          </View>
        ))}
      </View>
      <View style={styles.skeletonMap} />
      <View style={styles.skeletonCard}>
        <View style={styles.skeletonCardUpper}>
          <View style={styles.skeletonImage} />
          <View style={styles.skeletonCardCopy}>
            <View style={styles.skeletonName} />
            <View style={styles.skeletonMeta} />
          </View>
        </View>
        <View style={styles.skeletonButtons}>
          <View style={styles.skeletonVerify} />
          <View style={styles.skeletonVenue} />
        </View>
        <View style={styles.skeletonSeeWhos} />
      </View>
    </View>
  );
}

export function PresenceScreen() {
  const auth = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const retention = usePresenceRetention();
  const [selectedOverride, setSelectedOverride] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [useDevFixture, setUseDevFixture] = useState(false);
  const [devFixtureKind, setDevFixtureKind] = useState<
    "inside_entry" | "retention_only" | "outside_retention"
  >("inside_entry");

  useEffect(() => {
    if (!__DEV__) {
      return;
    }
    if (useDevFixture) {
      applyDevVenueFixture(devFixtureKind);
    } else {
      setDevLocationOverride(null);
    }
    return () => {
      setDevLocationOverride(null);
    };
  }, [useDevFixture, devFixtureKind]);

  const presenceQuery = useQuery({
    queryKey: ["presence", "me"],
    queryFn: fetchPresenceMe,
    enabled: auth.status === "authenticated",
    refetchInterval: 30_000,
  });

  const venuesQuery = useQuery({
    queryKey: ["map-venues", "presence", DEFAULT_CENTER, DEFAULT_RADIUS_M],
    queryFn: () =>
      fetchMapVenues({
        latitude: DEFAULT_CENTER.latitude,
        longitude: DEFAULT_CENTER.longitude,
        radius_m: DEFAULT_RADIUS_M,
        limit: 30,
      }),
    enabled: auth.status === "authenticated",
  });

  const venues = useMemo(() => venuesQuery.data?.items ?? [], [venuesQuery.data?.items]);
  const city = resolveDiscoverCity(venuesQuery.data?.items ?? venues);
  const presentation = resolvePresentationState(presenceQuery.data);
  const verifiedVenueId =
    presentation === "active" || presentation === "rechecking" || presentation === "grace"
      ? (presenceQuery.data?.venue?.id ?? null)
      : null;
  const presenceButtonLabel =
    presentation === "active" ||
    presentation === "rechecking" ||
    presentation === "grace"
      ? presenceStatusLabel(presentation)
      : null;
  const presenceStatusHint = presenceStatusSupportingCopy(presentation);

  const selectedVenueId = selectedOverride ?? verifiedVenueId ?? venues[0]?.id ?? null;

  const selected = useMemo(
    () => venues.find((venue) => venue.id === selectedVenueId) ?? null,
    [venues, selectedVenueId],
  );

  const verifiedAtSelected = Boolean(
    selected && verifiedVenueId && selected.id === verifiedVenueId,
  );

  const discoverableQuery = useQuery({
    queryKey: ["presence", "discoverable-users", verifiedVenueId],
    queryFn: fetchDiscoverableUsers,
    enabled: auth.status === "authenticated" && verifiedAtSelected,
  });

  const visiblePeople = useMemo(() => {
    if (!verifiedAtSelected) {
      return [];
    }
    const payload = discoverableQuery.data;
    if (!payload || payload.venue_id !== verifiedVenueId) {
      return [];
    }
    return payload.items.map((person) => ({
      user_id: person.user_id,
      handle: person.handle,
      display_name: person.display_name,
    }));
  }, [discoverableQuery.data, verifiedAtSelected, verifiedVenueId]);

  const verifyMutation = useVerifyPresence();
  const eligibility = usePresenceEligibility({
    venueId: selected?.id ?? null,
    enabled: auth.status === "authenticated" && Boolean(selected),
    locationSourceKey: useDevFixture ? "dev-fixture" : "device",
  });
  const canVerify =
    Boolean(selected) &&
    !isVerifiedAtVenue(presenceQuery.data, selected?.id ?? "") &&
    auth.status === "authenticated" &&
    eligibility.view?.eligible === true &&
    eligibility.view.venueId === selected?.id;

  const bottomPad = tabScreenBottomPadding(insets.bottom);
  const showSkeleton =
    auth.status === "authenticated" && venuesQuery.isLoading && !venuesQuery.data;

  if (auth.status === "unauthenticated") {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
        <View style={styles.signedOut} testID="presence-signed-out">
          <Text style={styles.signedOutTitle}>Presence</Text>
          <Text style={styles.signedOutBody}>Sign in to verify at a venue.</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Sign in"
            style={styles.signInButton}
            onPress={() => router.push("/auth/email")}
          >
            <Text style={styles.signInText}>Sign in</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  if (showSkeleton) {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="presence-screen">
        <View style={{ paddingBottom: bottomPad }}>
          <PresenceSkeleton />
        </View>
      </SafeAreaView>
    );
  }

  if (venuesQuery.isError && !venuesQuery.data) {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="presence-screen">
        <View style={styles.padded}>
          <TabScreenHeader title="Presence" location={city} testID="presence-header" />
        </View>
        <View style={styles.errorState} testID="presence-error-state">
          <Text style={styles.errorTitle}>Couldn’t load nearby venues</Text>
          <Text style={styles.errorBody}>Check your connection and try again.</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Retry"
            testID="presence-retry"
            style={styles.retryButton}
            onPress={() => {
              if (__DEV__) {
                console.warn("[presence]", venuesQuery.error);
              }
              void venuesQuery.refetch();
            }}
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  if (!venuesQuery.isLoading && venues.length === 0) {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="presence-screen">
        <View style={styles.padded}>
          <TabScreenHeader title="Presence" location={city} testID="presence-header" />
        </View>
        <View style={styles.emptyState} testID="presence-empty-state">
          <Text style={styles.errorTitle}>No venues found nearby</Text>
          <Text style={styles.errorBody}>Refresh your location or try another area.</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Refresh"
            testID="presence-empty-refresh"
            style={styles.retryButton}
            onPress={() => void venuesQuery.refetch()}
          >
            <Text style={styles.retryText}>Refresh</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="presence-screen">
      <PresenceLiveMap
        venues={venues}
        city={city}
        selectedVenueId={selectedVenueId}
        onSelectVenue={setSelectedOverride}
        verifiedVenueId={verifiedVenueId}
        canVerify={canVerify}
        verifying={verifyMutation.isPending}
        visiblePeople={visiblePeople}
        hereNowCount={null}
        eligibility={eligibility.view}
        eligibilityLoading={eligibility.loading}
        useDevFixture={useDevFixture}
        onToggleDevFixture={() => {
          if (!useDevFixture) {
            setDevFixtureKind("inside_entry");
            setUseDevFixture(true);
            return;
          }
          // Cycle: inside → retention-only → outside → off
          if (devFixtureKind === "inside_entry") {
            setDevFixtureKind("retention_only");
            return;
          }
          if (devFixtureKind === "retention_only") {
            setDevFixtureKind("outside_retention");
            return;
          }
          setUseDevFixture(false);
          setDevFixtureKind("inside_entry");
        }}
        onRefreshEligibility={eligibility.refresh}
        onVerify={() => {
          if (!selected || !canVerify) {
            return;
          }
          setActionError(null);
          void verifyMutation
            .mutateAsync({ candidateVenueId: selected.id })
            .then(async (snapshot) => {
              if (snapshot.state === "verified" && snapshot.venue) {
                await retention.requestBackgroundPermissionAfterVerify({
                  venueId: snapshot.venue.id,
                  latitude: selected.map_pin.latitude,
                  longitude: selected.map_pin.longitude,
                });
                router.push({
                  pathname: "/venue/[venueId]/verified",
                  params: {
                    venueId: snapshot.venue.id,
                    verifiedAt: new Date().toISOString(),
                  },
                });
              }
            })
            .catch((error: unknown) => {
              const mapped = friendlyVerifyError(error);
              setActionError(`${mapped.title}. ${mapped.body}`);
            })
            .finally(() => {
              eligibility.refresh();
            });
        }}
        onSeeWhosThere={() => router.push("/(tabs)/connect")}
        onOpenVenue={(venueId) => router.push(`/venue/${venueId}`)}
        onOpenFullscreenMap={() => router.push("/presence-map")}
        presenceButtonLabel={presenceButtonLabel}
        presenceStatusHint={presenceStatusHint}
        bottomClearance={bottomPad}
      />
      {actionError ? (
        <View style={styles.errorWrap}>
          <Text style={styles.actionError}>{actionError}</Text>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: PRESENCE_SURFACE.page,
  },
  padded: {
    paddingHorizontal: TAB_SCREEN_HORIZONTAL_PADDING,
  },
  signedOut: {
    flex: 1,
    padding: 24,
    justifyContent: "center",
    gap: 12,
  },
  signedOutTitle: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 40,
  },
  signedOutBody: {
    color: "rgba(255,255,255,0.55)",
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
  },
  signInButton: {
    marginTop: 8,
    minHeight: 48,
    borderRadius: 999,
    backgroundColor: PRESENCE_SURFACE.lime,
    alignItems: "center",
    justifyContent: "center",
  },
  signInText: {
    color: "#040907",
    fontFamily: fontFamilies.geistBold,
    fontSize: 15,
  },
  skeletonRoot: {
    paddingHorizontal: TAB_SCREEN_HORIZONTAL_PADDING,
    paddingTop: 10,
    gap: 4,
  },
  skeletonTitle: {
    width: 168,
    height: 40,
    borderRadius: 8,
    backgroundColor: "#121212",
  },
  skeletonCity: {
    width: 110,
    height: 15,
    borderRadius: 6,
    backgroundColor: "#1A1A1A",
  },
  skeletonStories: {
    flexDirection: "row",
    gap: 12,
  },
  skeletonStory: {
    width: PRESENCE_STORY_ITEM_WIDTH,
    alignItems: "center",
    gap: 8,
  },
  skeletonRing: {
    width: PRESENCE_STORY_RING,
    height: PRESENCE_STORY_RING,
    borderRadius: PRESENCE_STORY_RING / 2,
    borderWidth: 2,
    borderColor: "rgba(255,255,255,0.12)",
    backgroundColor: "#101010",
  },
  skeletonStoryName: {
    width: PRESENCE_STORY_IMAGE,
    height: 28,
    borderRadius: 6,
    backgroundColor: "#141414",
  },
  skeletonMap: {
    marginTop: 16,
    height: PRESENCE_MAP_HEIGHT,
    borderRadius: 22,
    backgroundColor: PRESENCE_SURFACE.map,
    borderWidth: 1,
    borderColor: PRESENCE_SURFACE.border,
  },
  skeletonCard: {
    marginTop: 16,
    borderRadius: 22,
    backgroundColor: PRESENCE_SURFACE.card,
    borderWidth: 1,
    borderColor: PRESENCE_SURFACE.border,
    padding: 12,
    gap: 12,
  },
  skeletonCardUpper: {
    flexDirection: "row",
    gap: 12,
    minHeight: 112,
  },
  skeletonImage: {
    width: 128,
    minHeight: 112,
    borderRadius: 16,
    backgroundColor: "#141414",
  },
  skeletonCardCopy: {
    flex: 1,
    gap: 10,
    paddingTop: 6,
  },
  skeletonName: {
    width: "80%",
    height: 28,
    borderRadius: 6,
    backgroundColor: "#161616",
  },
  skeletonMeta: {
    width: "60%",
    height: 14,
    borderRadius: 6,
    backgroundColor: "#121212",
  },
  skeletonButtons: {
    flexDirection: "row",
    gap: 10,
  },
  skeletonVerify: {
    flex: 1,
    height: 52,
    borderRadius: 16,
    backgroundColor: "#161616",
  },
  skeletonVenue: {
    flex: 0.55,
    height: 52,
    borderRadius: 16,
    backgroundColor: "#121212",
  },
  skeletonSeeWhos: {
    height: 52,
    borderRadius: 16,
    backgroundColor: "#121212",
  },
  errorState: {
    paddingHorizontal: TAB_SCREEN_HORIZONTAL_PADDING,
    paddingTop: 32,
    gap: 10,
  },
  emptyState: {
    paddingHorizontal: TAB_SCREEN_HORIZONTAL_PADDING,
    paddingTop: 32,
    gap: 10,
  },
  errorTitle: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
  },
  errorBody: {
    color: "rgba(255,255,255,0.55)",
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
  },
  retryButton: {
    marginTop: 8,
    alignSelf: "flex-start",
    minHeight: 44,
    paddingHorizontal: 18,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: PRESENCE_SURFACE.border,
    backgroundColor: "#0A0A0A",
    alignItems: "center",
    justifyContent: "center",
  },
  retryText: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 14,
  },
  errorWrap: {
    paddingHorizontal: TAB_SCREEN_HORIZONTAL_PADDING,
    paddingBottom: 12,
  },
  actionError: {
    color: "#FF6B6B",
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
});
