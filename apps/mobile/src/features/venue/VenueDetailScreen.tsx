import { useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useMemo, useState, type ReactNode } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";
import { fetchVenueDetail } from "@/features/discover/api";
import { formatDistanceLabel } from "@/features/discover/discoverPresentation";
import { fetchVenueVibes } from "@/features/experience/api";
import { fetchPresenceMe } from "@/features/presence/api";
import type { PresenceUserError } from "@/features/presence/presenceErrors";
import {
  friendlyVerifyError,
  interpretVerifyResult,
  useVerifyPresence,
} from "@/features/presence/useVerifyPresence";
import { VenueDetailSkeleton } from "@/features/venue/VenueDetailSkeleton";
import {
  VenueDetailErrorState,
  VenueDetailMissingState,
} from "@/features/venue/VenueDetailStates";
import { resolveVenueDisplaySource } from "@/features/venue/venueCategoryAssets";
import {
  pickApprovedLiveVibeImage,
  resolveLiveVibeMedia,
  resolveVenueIdentityImage,
} from "@/features/venue/venueImage";
import {
  formatClock,
  formatOpenState,
  formatRelativeAge,
  formatVenueCategory,
  formatVenueLocation,
  formatVisibilityLabel,
  isVenueMissingError,
  isVerifiedAtVenue,
  primaryVenueAction,
} from "@/features/venue/venuePresentation";
import { colors, fontFamilies } from "@/theme";

type Props = {
  venueId: string;
  distanceM?: number;
};

function InfoCard({
  title,
  children,
  testID,
}: {
  title: string;
  children: ReactNode;
  testID?: string;
}) {
  return (
    <View style={styles.card} testID={testID}>
      <Text style={styles.cardTitle}>{title}</Text>
      {children}
    </View>
  );
}

export function VenueDetailScreen({ venueId, distanceM }: Props) {
  const auth = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const heroHeight = Math.min(340, Math.max(280, Math.round(width * 0.78)));
  const stickyPad = Math.max(insets.bottom, 12);
  const stickyHeight = 72 + stickyPad;

  const [failedRemoteUri, setFailedRemoteUri] = useState<string | null>(null);
  const [verifyError, setVerifyError] = useState<PresenceUserError | null>(null);

  const detailQuery = useQuery({
    queryKey: ["venue", venueId],
    queryFn: () => fetchVenueDetail(venueId),
    enabled: Boolean(venueId) && auth.status === "authenticated",
    retry: false,
  });

  const presenceQuery = useQuery({
    queryKey: ["presence", "me"],
    queryFn: fetchPresenceMe,
    enabled: auth.status === "authenticated",
    refetchInterval: 30_000,
  });

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
  });

  const vibesQuery = useQuery({
    queryKey: ["venue", venueId, "vibes-preview"],
    queryFn: () => fetchVenueVibes(venueId),
    enabled: Boolean(venueId) && auth.status === "authenticated" && detailQuery.isSuccess,
    staleTime: 60_000,
  });

  const verifyMutation = useVerifyPresence();
  const [failedLiveVibeUri, setFailedLiveVibeUri] = useState<string | null>(null);

  const venue = detailQuery.data;
  const presence = presenceQuery.data;
  const verified = isVerifiedAtVenue(presence, venueId);
  const action = primaryVenueAction(verified);
  const livePreview = pickApprovedLiveVibeImage(vibesQuery.data?.items);
  const liveVibeMedia = useMemo(() => {
    if (!livePreview) {
      return resolveLiveVibeMedia({});
    }
    return resolveLiveVibeMedia({
      mediaUrl: livePreview.url,
      thumbnailUrl: livePreview.thumbnailUrl,
    });
  }, [livePreview]);
  const imageInputs = useMemo(
    () =>
      venue
        ? {
            venueId: venue.id,
            category: venue.category,
            venueName: venue.name,
            // Future: approvedCoverUrl / primaryGalleryImageUrl from owner media.
            // Live Vibes must never be passed into identity resolution.
          }
        : null,
    [venue],
  );
  const resolvedImage = useMemo(
    () => (imageInputs ? resolveVenueIdentityImage(imageInputs) : null),
    [imageInputs],
  );
  const remoteUri = resolvedImage?.kind === "remote" ? resolvedImage.uri : null;
  const imageSource = imageInputs
    ? resolveVenueDisplaySource(imageInputs, failedRemoteUri)
    : resolveVenueDisplaySource({ category: null, venueId: null });

  const goDiscover = () => {
    if (router.canGoBack()) {
      router.back();
      return;
    }
    router.replace("/(tabs)");
  };

  if (auth.status === "initializing" || (auth.status === "authenticated" && detailQuery.isLoading)) {
    return <VenueDetailSkeleton />;
  }

  if (auth.status === "unauthenticated") {
    return (
      <VenueDetailErrorState
        onRetry={() => router.replace("/auth")}
        onBack={goDiscover}
      />
    );
  }

  if (detailQuery.isError) {
    if (isVenueMissingError(detailQuery.error)) {
      return <VenueDetailMissingState onBack={goDiscover} />;
    }
    return (
      <VenueDetailErrorState
        onRetry={() => {
          void detailQuery.refetch();
        }}
        onBack={goDiscover}
      />
    );
  }

  if (!venue) {
    return <VenueDetailMissingState onBack={goDiscover} />;
  }

  const openState = formatOpenState(venue);
  const location = formatVenueLocation(venue);
  const distanceLabel = formatDistanceLabel(distanceM);
  const category = formatVenueCategory(venue.category);
  const tags = [...venue.music_tags, ...venue.experience_tags];
  const visibility = formatVisibilityLabel({
    ghostMode: meQuery.data?.privacy.ghost_mode || meQuery.data?.privacy.effective.ghost_mode_overrides,
    discoverableInVenue: meQuery.data?.privacy.effective.discoverable_in_venue,
    socialFeaturesEnabled: presence?.social_features_enabled,
  });
  const onPrimary = async () => {
    if (action.kind === "see_whos_here") {
      router.push("/(tabs)/connect");
      return;
    }
    if (verifyMutation.isPending) {
      return;
    }
    setVerifyError(null);
    try {
      const snapshot = await verifyMutation.mutateAsync({ candidateVenueId: venueId });
      const result = interpretVerifyResult(snapshot, venueId);
      if (!result.ok) {
        setVerifyError(result.error);
        return;
      }
      router.push({
        pathname: "/venue/[venueId]/verified",
        params: {
          venueId,
          verifiedAt: new Date().toISOString(),
        },
      });
    } catch (error) {
      if (__DEV__) {
        console.warn("[presence.verify]", error);
      }
      setVerifyError(friendlyVerifyError(error));
    }
  };

  return (
    <View style={styles.root} testID="venue-detail">
      <ScrollView
        contentContainerStyle={{ paddingBottom: stickyHeight + 24 }}
        showsVerticalScrollIndicator={false}
      >
        <View style={[styles.hero, { height: heroHeight }]}>
          <Image
            source={imageSource}
            style={StyleSheet.absoluteFill}
            contentFit="cover"
            transition={0}
            onError={() => {
              if (remoteUri) {
                setFailedRemoteUri(remoteUri);
              }
            }}
            accessibilityLabel={`${venue.name} cover image`}
          />
          <LinearGradient
            colors={[colors.overlayTop, "transparent", colors.overlayBottom]}
            locations={[0, 0.4, 1]}
            style={StyleSheet.absoluteFill}
          />
          <View style={[styles.heroControls, { paddingTop: insets.top + 8 }]}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Go back"
              testID="venue-detail-back"
              hitSlop={8}
              onPress={goDiscover}
              style={({ pressed }) => [styles.circleBtn, pressed && styles.pressed]}
            >
              <Text style={styles.circleBtnIcon}>←</Text>
            </Pressable>
          </View>
        </View>

        <View style={styles.content}>
          <View style={styles.nameRow}>
            <Text style={styles.name} accessibilityRole="header">
              {venue.name}
            </Text>
            <View style={styles.categoryBadge}>
              <Text style={styles.categoryText}>{category}</Text>
            </View>
          </View>

          <Text style={styles.statusLine} accessibilityLabel={[openState, location, distanceLabel].filter(Boolean).join(", ")}>
            {openState ? <Text style={styles.openLive}>{openState}</Text> : null}
            {openState ? <Text style={styles.metaMuted}> · </Text> : null}
            <Text style={styles.metaMuted}>{location}</Text>
            {distanceLabel ? <Text style={styles.metaMuted}>{` · ${distanceLabel}`}</Text> : null}
          </Text>

          {venue.description ? (
            <Text style={styles.description}>{venue.description}</Text>
          ) : null}

          {tags.length > 0 ? (
            <View style={styles.tagRow}>
              {tags.map((tag) => (
                <View key={tag} style={styles.tag}>
                  <Text style={styles.tagText}>{tag.replaceAll("_", " ")}</Text>
                </View>
              ))}
            </View>
          ) : null}

          {livePreview ? (
            <InfoCard title="LIVE VIBE" testID="venue-live-vibe-card">
              <View style={styles.liveRow}>
                {liveVibeMedia.kind === "remote" &&
                failedLiveVibeUri !== liveVibeMedia.uri ? (
                  <Image
                    source={{ uri: liveVibeMedia.uri }}
                    style={styles.liveThumb}
                    contentFit="cover"
                    onError={() => setFailedLiveVibeUri(liveVibeMedia.uri)}
                    accessibilityLabel="Approved Live Vibe preview"
                    testID="venue-live-vibe-thumb"
                  />
                ) : (
                  <View
                    style={styles.liveThumbFailed}
                    accessibilityLabel="Couldn’t load this vibe"
                    testID="venue-live-vibe-thumb-failed"
                  >
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel="Try again"
                      onPress={() => setFailedLiveVibeUri(null)}
                      style={styles.liveThumbRetry}
                    >
                      <Text style={styles.liveThumbRetryText}>Try again</Text>
                    </Pressable>
                  </View>
                )}
                <View style={styles.liveCopy}>
                  <Text style={styles.cardBody}>Latest approved vibe</Text>
                  <Text style={styles.cardMeta}>
                    {formatRelativeAge(livePreview.publishedAt) ?? "Recently"}
                  </Text>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="View Live Vibes"
                    onPress={() => router.push("/(tabs)/experience")}
                    style={styles.linkBtn}
                  >
                    <Text style={styles.linkText}>VIEW LIVE VIBES</Text>
                  </Pressable>
                </View>
              </View>
            </InfoCard>
          ) : null}

          <InfoCard title="VENUE EXPERIENCE" testID="venue-experience-card">
            <Text style={styles.cardBody}>Category · {category}</Text>
            {tags.length > 0 ? (
              <Text style={styles.cardMeta}>{tags.map((t) => t.replaceAll("_", " ")).join(" · ")}</Text>
            ) : null}
            {openState ? <Text style={styles.cardAccent}>{openState}</Text> : null}
            {venue.status === "active" ? (
              <Text style={styles.cardMeta}>Venue listed as active</Text>
            ) : (
              <Text style={styles.cardMeta}>Status · {venue.status}</Text>
            )}
          </InfoCard>

          <InfoCard title="YOUR PRESENCE" testID="venue-presence-card">
            {verified ? (
              <>
                <Text style={styles.cardAccent} accessibilityLiveRegion="polite">
                  Verified at this venue
                </Text>
                <Text style={styles.cardBody}>
                  Expires {formatClock(presence?.lease_expires_at, venue.timezone)}
                </Text>
                <Text style={styles.cardMeta}>Visibility · {visibility}</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="See who’s here"
                  onPress={() => router.push("/(tabs)/connect")}
                  style={styles.linkBtn}
                >
                  <Text style={styles.linkText}>SEE WHO’S HERE</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Text style={styles.cardBody}>You are not verified here</Text>
                <Text style={styles.cardMeta}>
                  You must be physically near the venue to verify your presence.
                </Text>
              </>
            )}
          </InfoCard>

          {verifyError ? (
            <View
              style={styles.errorBanner}
              accessibilityLiveRegion="polite"
              testID="venue-verify-error"
            >
              <Text style={styles.errorTitle}>{verifyError.title}</Text>
              <Text style={styles.errorBody}>{verifyError.body}</Text>
            </View>
          ) : null}
        </View>
      </ScrollView>

      <View
        style={[styles.sticky, { paddingBottom: stickyPad }]}
        testID="venue-sticky-action"
      >
        <View style={styles.stickyCopy}>
          <Text style={styles.stickyLabel}>
            {verified ? "PRESENCE" : "AT THIS VENUE"}
          </Text>
          <Text style={styles.stickyValue} numberOfLines={2}>
            {verified
              ? `Until ${formatClock(presence?.lease_expires_at, venue.timezone)}`
              : "Verify to connect"}
          </Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={action.accessibilityLabel}
          accessibilityState={{ disabled: verifyMutation.isPending, busy: verifyMutation.isPending }}
          testID="venue-primary-action"
          disabled={verifyMutation.isPending}
          onPress={() => {
            void onPrimary();
          }}
          style={({ pressed }) => [
            styles.primaryBtn,
            (pressed || verifyMutation.isPending) && styles.pressed,
            verifyMutation.isPending && styles.primaryDisabled,
          ]}
        >
          <Text style={styles.primaryBtnText}>
            {verifyMutation.isPending ? "VERIFYING…" : action.label}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  hero: {
    width: "100%",
    backgroundColor: colors.surface,
    overflow: "hidden",
  },
  heroControls: {
    position: "absolute",
    left: 16,
    right: 16,
    top: 0,
    flexDirection: "row",
    justifyContent: "space-between",
  },
  circleBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceTranslucent,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  circleBtnIcon: {
    color: colors.textPrimary,
    fontSize: 20,
    fontFamily: fontFamilies.geistSemiBold,
    marginTop: -1,
  },
  content: {
    paddingHorizontal: 20,
    paddingTop: 18,
    gap: 14,
  },
  nameRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  name: {
    flex: 1,
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 34,
    lineHeight: 38,
  },
  categoryBadge: {
    marginTop: 6,
    minHeight: 28,
    paddingHorizontal: 10,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(226, 184, 87, 0.16)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(226, 184, 87, 0.45)",
  },
  categoryText: {
    color: colors.gold,
    fontFamily: fontFamilies.geistBold,
    fontSize: 11,
    letterSpacing: 0.5,
  },
  statusLine: {
    flexWrap: "wrap",
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  openLive: {
    color: colors.lime,
    fontFamily: fontFamilies.geistBold,
    letterSpacing: 0.4,
  },
  metaMuted: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
  },
  description: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
    lineHeight: 23,
  },
  tagRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  tag: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  tagText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
    textTransform: "capitalize",
  },
  card: {
    borderRadius: 18,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 16,
    gap: 8,
  },
  cardTitle: {
    color: colors.gold,
    fontFamily: fontFamilies.geistBold,
    fontSize: 11,
    letterSpacing: 1.2,
  },
  cardBody: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 14,
    lineHeight: 20,
  },
  cardMeta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    lineHeight: 19,
  },
  cardAccent: {
    color: colors.lime,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 14,
  },
  liveRow: { flexDirection: "row", gap: 12, alignItems: "center" },
  liveThumb: {
    width: 64,
    height: 64,
    borderRadius: 12,
    backgroundColor: colors.background,
  },
  liveThumbFailed: {
    width: 64,
    height: 64,
    borderRadius: 12,
    backgroundColor: "#111111",
    alignItems: "center",
    justifyContent: "center",
  },
  liveThumbRetry: {
    paddingHorizontal: 6,
    paddingVertical: 4,
  },
  liveThumbRetryText: {
    color: "rgba(255,255,255,0.7)",
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 10,
  },
  liveCopy: { flex: 1, gap: 4 },
  linkBtn: {
    marginTop: 4,
    minHeight: 36,
    justifyContent: "center",
    alignSelf: "flex-start",
  },
  linkText: {
    color: colors.lime,
    fontFamily: fontFamilies.geistBold,
    fontSize: 12,
    letterSpacing: 0.8,
  },
  errorBanner: {
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(255, 107, 107, 0.45)",
    backgroundColor: "rgba(255, 107, 107, 0.08)",
    padding: 14,
    gap: 4,
  },
  errorTitle: {
    color: colors.danger,
    fontFamily: fontFamilies.geistBold,
    fontSize: 14,
  },
  errorBody: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    lineHeight: 19,
  },
  sticky: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingTop: 12,
    backgroundColor: "rgba(4, 9, 7, 0.94)",
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  stickyCopy: { flex: 1, gap: 2 },
  stickyLabel: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 11,
    letterSpacing: 1,
  },
  stickyValue: {
    color: colors.lime,
    fontFamily: fontFamilies.geistBold,
    fontSize: 16,
  },
  primaryBtn: {
    minHeight: 52,
    minWidth: 148,
    maxWidth: "58%",
    paddingHorizontal: 18,
    borderRadius: 26,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryBtnText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 13,
    textAlign: "center",
  },
  primaryDisabled: { opacity: 0.7 },
  pressed: { opacity: 0.88 },
});
