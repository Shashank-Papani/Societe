import { Image } from "expo-image";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  FlatList,
  type LayoutChangeEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";

import {
  TabScreenHeader,
  TAB_SCREEN_HORIZONTAL_PADDING,
} from "@/components/TabScreenHeader";
import type { VenueCard } from "@/features/discover/api";
import { ProfileAvatar } from "@/features/connect/ProfileAvatar";
import { formatVenueTypeTitle } from "@/features/discover/discoverPresentation";
import { PresenceEligibilityDiagnostics } from "@/features/presence/PresenceEligibilityDiagnostics";
import {
  formatPresenceMetaWithDistance,
  mapEligibilityReasonToButtonLabel,
  type PresenceEligibilityView,
} from "@/features/presence/presenceEligibility";
import {
  PRESENCE_LOCATION_TO_STORIES_GAP,
  PRESENCE_MAP_HEIGHT,
  PRESENCE_STORY_GAP,
  PRESENCE_STORY_IMAGE,
  PRESENCE_STORY_ITEM_WIDTH,
  PRESENCE_STORY_NAME_SIZE,
  PRESENCE_STORY_RING,
  PRESENCE_SURFACE,
  presenceAvatarAccessibilityLabel,
  projectVenuePins,
  visiblePeopleForStack,
  type PresencePerson,
} from "@/features/presence/presencePresentation";
import { resolveVenueDisplaySource } from "@/features/venue/venueCategoryAssets";
import { noirIcons } from "@/icons/noirIcons";
import { getMapProvider } from "@/maps/MapProvider";
import { fontFamilies } from "@/theme";

type Props = {
  venues: VenueCard[];
  city: string;
  selectedVenueId: string | null;
  onSelectVenue: (venueId: string) => void;
  verifiedVenueId: string | null;
  canVerify: boolean;
  verifying: boolean;
  onVerify: () => void;
  onSeeWhosThere: () => void;
  onOpenVenue: (venueId: string) => void;
  onOpenFullscreenMap: () => void;
  /** Privacy-gated discoverable people for the verified selected venue. */
  visiblePeople?: PresencePerson[];
  /** Real aggregate only — never invent. */
  hereNowCount?: number | null;
  eligibility: PresenceEligibilityView | null;
  eligibilityLoading: boolean;
  useDevFixture: boolean;
  onToggleDevFixture: () => void;
  onRefreshEligibility: () => void;
  /** Overrides verify button when presence is active / rechecking / grace. */
  presenceButtonLabel?: string | null;
  presenceStatusHint?: string | null;
  /** Single source of truth for clearance above the tab bar. */
  bottomClearance: number;
};

export function PresenceLiveMap({
  venues,
  city,
  selectedVenueId,
  onSelectVenue,
  verifiedVenueId,
  canVerify,
  verifying,
  onVerify,
  onSeeWhosThere,
  onOpenVenue,
  onOpenFullscreenMap,
  visiblePeople = [],
  hereNowCount = null,
  eligibility,
  eligibilityLoading,
  useDevFixture,
  onToggleDevFixture,
  onRefreshEligibility,
  presenceButtonLabel = null,
  presenceStatusHint = null,
  bottomClearance,
}: Props) {
  const provider = getMapProvider();
  const storiesRef = useRef<FlatList<VenueCard>>(null);
  const { width: windowWidth } = useWindowDimensions();
  const [mapSize, setMapSize] = useState({ width: windowWidth - 32, height: PRESENCE_MAP_HEIGHT });

  const selected =
    venues.find((venue) => venue.id === selectedVenueId) ?? venues[0] ?? null;

  const pins = useMemo(
    () =>
      provider.listPins(
        { center: { latitude: 34.0955, longitude: -118.344 }, radius_m: 8000 },
        venues.map((venue) => ({
          id: venue.id,
          title: venue.name,
          category: venue.category,
          distance_m: venue.distance_m,
          coordinate: {
            latitude: venue.map_pin.latitude,
            longitude: venue.map_pin.longitude,
          },
        })),
      ),
    [provider, venues],
  );

  const projected = useMemo(
    () =>
      projectVenuePins(
        pins.map((pin) => ({
          id: pin.id,
          latitude: pin.coordinate.latitude,
          longitude: pin.coordinate.longitude,
        })),
        mapSize.width,
        mapSize.height,
      ),
    [pins, mapSize.height, mapSize.width],
  );

  const selectedIndex = selected
    ? venues.findIndex((venue) => venue.id === selected.id)
    : -1;

  useEffect(() => {
    if (selectedIndex < 0 || !storiesRef.current) {
      return;
    }
    try {
      storiesRef.current.scrollToIndex({
        index: selectedIndex,
        animated: true,
        viewPosition: 0.35,
      });
    } catch {
      // FlatList may not be measured yet on first select.
    }
  }, [selectedIndex]);

  const verifiedAtSelected = Boolean(
    selected && verifiedVenueId && verifiedVenueId === selected.id,
  );
  const stack = verifiedAtSelected ? visiblePeopleForStack(visiblePeople) : null;
  const narrow = windowWidth < 360;
  const imageWidth = narrow ? 112 : 128;

  const eligibilityForSelected =
    eligibility && selected && eligibility.venueId === selected.id ? eligibility : null;
  const reason = verifiedAtSelected
    ? ("already_verified" as const)
    : eligibilityLoading || !eligibilityForSelected
      ? ("loading" as const)
      : eligibilityForSelected.reason;
  const verifyLabel =
    presenceButtonLabel ?? mapEligibilityReasonToButtonLabel(reason, { verifying });
  const verifyEnabled =
    Boolean(selected) &&
    canVerify &&
    !verifying &&
    !verifiedAtSelected &&
    !presenceButtonLabel &&
    !eligibilityLoading &&
    eligibilityForSelected?.eligible === true;
  const metaLine = selected
    ? formatPresenceMetaWithDistance({
        category: selected.category,
        distanceMeters:
          eligibilityForSelected && !eligibilityLoading
            ? eligibilityForSelected.distanceMeters
            : null,
        distancePending: Boolean(selected) && (eligibilityLoading || !eligibilityForSelected),
        hereNowCount,
        formatVenueType: formatVenueTypeTitle,
      })
    : "";

  const onMapLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    if (width > 0 && height > 0) {
      setMapSize({ width, height });
    }
  };

  const handleSeeWhosThere = () => {
    if (!verifiedAtSelected) {
      Alert.alert("Presence required", "Verify your presence to see who’s there.");
      return;
    }
    onSeeWhosThere();
  };

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={[styles.content, { paddingBottom: bottomClearance }]}
      showsVerticalScrollIndicator={false}
      testID="presence-live-map"
    >
      <View style={styles.padded}>
        <TabScreenHeader
          title="Presence"
          location={city}
          testID="presence-header"
          locationTestID="presence-city"
        />
      </View>

      <FlatList
        ref={storiesRef}
        data={venues}
        keyExtractor={(item) => item.id}
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.storiesList}
        contentContainerStyle={styles.stories}
        ItemSeparatorComponent={() => <View style={{ width: PRESENCE_STORY_GAP }} />}
        onScrollToIndexFailed={(info) => {
          storiesRef.current?.scrollToOffset({
            offset: Math.max(0, info.index * (PRESENCE_STORY_ITEM_WIDTH + PRESENCE_STORY_GAP)),
            animated: true,
          });
        }}
        testID="presence-venue-circles"
        renderItem={({ item: venue }) => {
          const selectedCircle = selected?.id === venue.id;
          const image = resolveVenueDisplaySource({
            venueId: venue.id,
            category: venue.category,
            venueName: venue.name,
          });
          const viewed = !selectedCircle;
          return (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${venue.name}${selectedCircle ? ", selected" : ""}${viewed ? ", viewed" : ", unviewed"}`}
              accessibilityState={{ selected: selectedCircle }}
              testID={`presence-circle-${venue.id}`}
              onPress={() => onSelectVenue(venue.id)}
              style={styles.circleItem}
            >
              <View
                style={[
                  styles.circleRing,
                  selectedCircle ? styles.circleRingActive : styles.circleRingInactive,
                ]}
              >
                <Image source={image} style={styles.circleImage} contentFit="cover" />
              </View>
              <Text
                style={styles.circleName}
                numberOfLines={2}
                ellipsizeMode="tail"
                testID={`presence-circle-name-${venue.id}`}
              >
                {venue.name}
              </Text>
            </Pressable>
          );
        }}
      />

      <View style={styles.padded}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Open nearby venue map"
          testID="presence-map-surface"
          onPress={onOpenFullscreenMap}
          onLayout={onMapLayout}
          style={styles.mapSurface}
        >
          <View style={styles.mapCanvas} pointerEvents="box-none">
            <View style={styles.mapRoadH1} />
            <View style={styles.mapRoadH2} />
            <View style={styles.mapRoadV1} />
            <View style={styles.mapRoadV2} />
            <Text style={styles.mapLabel}>Nearby venues</Text>
            {projected.map((point) => {
              const active = selected?.id === point.id;
              const pin = pins.find((p) => p.id === point.id);
              return (
                <Pressable
                  key={point.id}
                  accessibilityRole="button"
                  accessibilityLabel={`${pin?.title ?? "Venue"} pin`}
                  accessibilityState={{ selected: active }}
                  testID={`presence-map-pin-${point.id}`}
                  onPress={() => onSelectVenue(point.id)}
                  style={[
                    styles.mapPin,
                    active ? styles.mapPinActive : styles.mapPinMuted,
                    {
                      left: point.x - 6,
                      top: point.y - 6,
                    },
                  ]}
                />
              );
            })}
          </View>
          {__DEV__ && !provider.isNativeMapAvailable ? (
            <Text style={styles.devMapNote} testID="presence-map-dev-note">
              {`Map provider: ${provider.name} (native SDK unavailable)`}
            </Text>
          ) : null}
        </Pressable>

        {selected ? (
          <View
            style={styles.selectedCard}
            testID="presence-selected-card"
            accessibilityLabel={`Selected venue ${selected.name}`}
          >
            <View style={styles.upperRow}>
              <Image
                source={resolveVenueDisplaySource({
                  venueId: selected.id,
                  category: selected.category,
                  venueName: selected.name,
                })}
                style={[styles.selectedImage, { width: imageWidth }]}
                contentFit="cover"
                testID="presence-selected-image"
              />
              <View style={styles.selectedCopy}>
                <Text
                  style={styles.selectedName}
                  numberOfLines={2}
                  testID="presence-selected-name"
                >
                  {selected.name}
                </Text>
                <Text style={styles.selectedMeta} testID="presence-selected-meta">
                  {metaLine}
                </Text>
                {stack && stack.visible.length > 0 ? (
                  <View
                    style={styles.avatarStack}
                    testID="presence-avatar-stack"
                    accessibilityLabel={presenceAvatarAccessibilityLabel(
                      selected.name,
                      visiblePeople.length,
                    )}
                  >
                    {stack.visible.map((person, index) => (
                      <View
                        key={person.user_id}
                        style={[styles.avatarWrap, { marginLeft: index === 0 ? 0 : -9, zIndex: 10 - index }]}
                      >
                        <ProfileAvatar
                          displayName={person.display_name}
                          handle={person.handle}
                          photoUrl={person.profile_photo_url}
                          size={30}
                          testID={`presence-avatar-${person.user_id}`}
                        />
                      </View>
                    ))}
                    {stack.overflow > 0 ? (
                      <View
                        style={[styles.avatarOverflow, { marginLeft: -9 }]}
                        testID="presence-avatar-overflow"
                      >
                        <Text style={styles.avatarOverflowText}>+{stack.overflow}</Text>
                      </View>
                    ) : null}
                  </View>
                ) : null}
              </View>
            </View>

            <View style={styles.primaryButtons}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={verifyLabel}
                accessibilityState={{
                  disabled: !verifyEnabled,
                }}
                disabled={!verifyEnabled}
                testID="presence-verify-selected"
                onPress={onVerify}
                style={[styles.verifyBtn, !verifyEnabled && styles.verifyDisabled]}
              >
                <Text style={styles.verifyText}>{verifyLabel}</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Open venue detail"
                testID="presence-venue-button"
                onPress={() => onOpenVenue(selected.id)}
                style={styles.venueBtn}
              >
                <Text style={styles.neutralBtnText}>Venue</Text>
              </Pressable>
            </View>
            {presenceStatusHint ? (
              <Text
                style={styles.presenceHint}
                accessibilityLiveRegion="polite"
                testID="presence-status-hint"
              >
                {presenceStatusHint}
              </Text>
            ) : null}

            <Pressable
              accessibilityRole="button"
              accessibilityLabel={
                verifiedAtSelected
                  ? "See who’s there"
                  : "See who’s there. Verify your presence to see who’s there."
              }
              accessibilityState={{ disabled: !verifiedAtSelected }}
              testID="presence-see-whos-there"
              onPress={handleSeeWhosThere}
              style={[styles.seeWhosThereBtn, !verifiedAtSelected && styles.seeWhosDisabled]}
            >
              <Image
                source={noirIcons.connectMuted}
                style={styles.seeWhosIcon}
                contentFit="contain"
                accessibilityIgnoresInvertColors
              />
              <Text style={styles.neutralBtnText}>See who’s there</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.emptyInline} testID="presence-empty-inline">
            <Text style={styles.emptyTitle}>No venues found nearby</Text>
            <Text style={styles.emptyBody}>
              Refresh your location or try another area.
            </Text>
          </View>
        )}

        <PresenceEligibilityDiagnostics
          eligibility={eligibilityForSelected}
          venueLatitude={selected?.map_pin.latitude}
          venueLongitude={selected?.map_pin.longitude}
          useDevFixture={useDevFixture}
          onToggleDevFixture={onToggleDevFixture}
          onRefresh={onRefreshEligibility}
        />
      </View>
    </ScrollView>
  );
}

const RING_PAD = (PRESENCE_STORY_RING - PRESENCE_STORY_IMAGE) / 2;

const SELECTED_IMAGE_HEIGHT = 112;

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: PRESENCE_SURFACE.page,
  },
  content: {
    // Bottom clearance is applied via bottomClearance prop — do not double-count.
    flexGrow: 0,
  },
  padded: {
    paddingHorizontal: TAB_SCREEN_HORIZONTAL_PADDING,
  },
  storiesList: {
    marginTop: PRESENCE_LOCATION_TO_STORIES_GAP,
    flexGrow: 0,
  },
  stories: {
    paddingHorizontal: TAB_SCREEN_HORIZONTAL_PADDING,
    paddingRight: TAB_SCREEN_HORIZONTAL_PADDING + 8,
  },
  circleItem: {
    width: PRESENCE_STORY_ITEM_WIDTH,
    alignItems: "center",
    gap: 8,
  },
  circleRing: {
    width: PRESENCE_STORY_RING,
    height: PRESENCE_STORY_RING,
    borderRadius: PRESENCE_STORY_RING / 2,
    alignItems: "center",
    justifyContent: "center",
    padding: RING_PAD,
  },
  circleRingActive: {
    borderWidth: 2.5,
    borderColor: PRESENCE_SURFACE.lime,
  },
  circleRingInactive: {
    borderWidth: 1.75,
    borderColor: PRESENCE_SURFACE.ringInactive,
  },
  circleImage: {
    width: PRESENCE_STORY_IMAGE,
    height: PRESENCE_STORY_IMAGE,
    borderRadius: PRESENCE_STORY_IMAGE / 2,
  },
  circleName: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: PRESENCE_STORY_NAME_SIZE,
    fontWeight: "600",
    lineHeight: 17,
    textAlign: "center",
    width: PRESENCE_STORY_ITEM_WIDTH,
  },
  mapSurface: {
    marginTop: 16,
    height: PRESENCE_MAP_HEIGHT,
    borderRadius: 22,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: PRESENCE_SURFACE.border,
    backgroundColor: PRESENCE_SURFACE.map,
  },
  mapCanvas: {
    flex: 1,
    backgroundColor: "#050505",
  },
  mapRoadH1: {
    position: "absolute",
    left: 0,
    right: 0,
    top: "38%",
    height: StyleSheet.hairlineWidth,
    backgroundColor: "rgba(255,255,255,0.06)",
  },
  mapRoadH2: {
    position: "absolute",
    left: 0,
    right: 0,
    top: "62%",
    height: StyleSheet.hairlineWidth,
    backgroundColor: "rgba(255,255,255,0.05)",
  },
  mapRoadV1: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: "32%",
    width: StyleSheet.hairlineWidth,
    backgroundColor: "rgba(255,255,255,0.05)",
  },
  mapRoadV2: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: "68%",
    width: StyleSheet.hairlineWidth,
    backgroundColor: "rgba(255,255,255,0.04)",
  },
  mapLabel: {
    position: "absolute",
    left: 14,
    top: 12,
    color: "rgba(255,255,255,0.45)",
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
  },
  mapPin: {
    position: "absolute",
    width: 12,
    height: 12,
    borderRadius: 6,
  },
  mapPinActive: {
    backgroundColor: PRESENCE_SURFACE.lime,
    width: 14,
    height: 14,
    borderRadius: 7,
  },
  mapPinMuted: {
    backgroundColor: PRESENCE_SURFACE.pinMuted,
  },
  devMapNote: {
    position: "absolute",
    left: 10,
    bottom: 8,
    color: "rgba(255,255,255,0.35)",
    fontFamily: fontFamilies.geistRegular,
    fontSize: 10,
  },
  selectedCard: {
    marginTop: 16,
    borderRadius: 22,
    backgroundColor: PRESENCE_SURFACE.card,
    borderWidth: 1,
    borderColor: PRESENCE_SURFACE.border,
    // Content-driven height; image uses a fixed pixel height so overflow clipping
    // cannot hide the action buttons after a stale percentage-height layout pass.
    overflow: "hidden",
    padding: 12,
    gap: 12,
  },
  upperRow: {
    flexDirection: "row",
    gap: 12,
    alignItems: "flex-start",
  },
  selectedImage: {
    height: SELECTED_IMAGE_HEIGHT,
    borderRadius: 16,
    overflow: "hidden",
  },
  selectedCopy: {
    flexShrink: 1,
    flexGrow: 1,
    gap: 8,
    justifyContent: "flex-start",
    paddingTop: 2,
  },
  selectedName: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
    lineHeight: 32,
  },
  selectedMeta: {
    color: "rgba(255,255,255,0.62)",
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
    lineHeight: 17,
  },
  avatarStack: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 2,
    minHeight: 34,
  },
  avatarWrap: {
    borderWidth: 2,
    borderColor: PRESENCE_SURFACE.card,
    borderRadius: 17,
  },
  avatarOverflow: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: "#161616",
    borderWidth: 2,
    borderColor: PRESENCE_SURFACE.card,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarOverflowText: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 11,
  },
  primaryButtons: {
    flexDirection: "row",
    gap: 10,
  },
  verifyBtn: {
    flex: 1,
    minHeight: 52,
    borderRadius: 16,
    backgroundColor: PRESENCE_SURFACE.lime,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 12,
  },
  verifyDisabled: {
    opacity: 0.72,
  },
  verifyText: {
    color: "#040907",
    fontFamily: fontFamilies.geistBold,
    fontSize: 15,
  },
  presenceHint: {
    color: "rgba(255,255,255,0.55)",
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  venueBtn: {
    flexGrow: 0,
    flexShrink: 0,
    flexBasis: "34%",
    minHeight: 52,
    borderRadius: 16,
    backgroundColor: "#000000",
    borderWidth: 1,
    borderColor: PRESENCE_SURFACE.border,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 12,
  },
  seeWhosThereBtn: {
    width: "100%",
    minHeight: 52,
    borderRadius: 16,
    backgroundColor: "#000000",
    borderWidth: 1,
    borderColor: PRESENCE_SURFACE.border,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 8,
  },
  seeWhosDisabled: {
    opacity: 0.55,
  },
  seeWhosIcon: {
    width: 18,
    height: 18,
  },
  neutralBtnText: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 15,
  },
  emptyInline: {
    marginTop: 24,
    gap: 8,
    paddingVertical: 24,
  },
  emptyTitle: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
  },
  emptyBody: {
    color: "rgba(255,255,255,0.55)",
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
  },
});
