import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { VenueCard } from "@/features/discover/api";
import {
  discoverSurface,
  formatCrowdRow,
  formatPrimaryMetaSegments,
  venueAccessibilityLabel,
} from "@/features/discover/discoverPresentation";
import { resolveVenueDisplaySource } from "@/features/venue/venueCategoryAssets";
import { resolveVenueIdentityImage } from "@/features/venue/venueImage";
import { noirIcons } from "@/icons/noirIcons";
import { fontFamilies } from "@/theme";

type Props = {
  venue: VenueCard;
  saved?: boolean;
  onToggleSaved?: (venueId: string) => void;
  testID?: string;
};

export function VenueCardView({ venue, saved = false, onToggleSaved, testID }: Props) {
  const router = useRouter();
  const [failedRemoteUri, setFailedRemoteUri] = useState<string | null>(null);
  const metaSegments = formatPrimaryMetaSegments(venue);
  const crowd = formatCrowdRow(venue);

  const imageInputs = useMemo(
    () => ({
      category: venue.category,
      venueId: venue.id,
      venueName: venue.name,
      // Future approved owner media fields (cover/gallery) plug in here.
    }),
    [venue.category, venue.id, venue.name],
  );
  const resolvedImage = useMemo(
    () => resolveVenueIdentityImage(imageInputs),
    [imageInputs],
  );
  const remoteUri = resolvedImage.kind === "remote" ? resolvedImage.uri : null;
  const imageSource = resolveVenueDisplaySource(imageInputs, failedRemoteUri);

  const openVenue = () => {
    router.push({
      pathname: "/venue/[venueId]",
      params: {
        venueId: venue.id,
        ...(typeof venue.distance_m === "number"
          ? { distance_m: String(venue.distance_m) }
          : {}),
      },
    });
  };

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={venueAccessibilityLabel(venue)}
      testID={testID ?? `venue-card-${venue.id}`}
      onPress={openVenue}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <Image
        source={imageSource}
        style={StyleSheet.absoluteFill}
        contentFit="cover"
        transition={200}
        accessibilityIgnoresInvertColors
        onError={() => {
          if (remoteUri) {
            setFailedRemoteUri(remoteUri);
          }
        }}
      />
      <LinearGradient
        colors={["transparent", "rgba(0,0,0,0.18)", "rgba(0,0,0,0.94)"]}
        locations={[0, 0.4, 1]}
        style={styles.gradient}
        testID={`venue-card-gradient-${venue.id}`}
      />

      <View style={styles.footer} pointerEvents="box-none">
        <View style={styles.copy} pointerEvents="none">
          <Text style={styles.name} numberOfLines={2} testID={`venue-name-${venue.id}`}>
            {venue.name}
          </Text>
          <Text style={styles.metaLine} numberOfLines={2} testID={`venue-meta-${venue.id}`}>
            {metaSegments.map((segment, index) => (
              <Text
                key={`${segment.text}-${index}`}
                style={
                  segment.tone === "open"
                    ? styles.metaOpen
                    : segment.tone === "closed"
                      ? styles.metaClosed
                      : segment.tone === "separator"
                        ? styles.metaSeparator
                        : styles.metaMuted
                }
              >
                {segment.text}
              </Text>
            ))}
          </Text>
          {crowd ? (
            <View style={styles.crowdRow} testID={`venue-crowd-${venue.id}`}>
              <Image
                source={noirIcons.locationPinLime}
                style={styles.crowdIcon}
                contentFit="contain"
                accessibilityIgnoresInvertColors
              />
              <Text style={styles.crowdText}>{crowd.text}</Text>
            </View>
          ) : null}
        </View>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={
            saved ? `Remove ${venue.name} from saved venues` : `Save ${venue.name}`
          }
          accessibilityState={{ selected: saved }}
          testID={`venue-favorite-${venue.id}`}
          hitSlop={8}
          onPress={(event) => {
            // Prevent opening Venue Detail when toggling favorite.
            event?.stopPropagation?.();
            onToggleSaved?.(venue.id);
          }}
          style={({ pressed }) => [styles.heartButton, pressed && styles.heartPressed]}
        >
          <Image
            source={saved ? noirIcons.heartFilledLime : noirIcons.heartOutlineWhite}
            style={styles.heartIcon}
            contentFit="contain"
            accessibilityIgnoresInvertColors
            testID={
              saved ? `venue-heart-filled-${venue.id}` : `venue-heart-outline-${venue.id}`
            }
          />
        </Pressable>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    width: "100%",
    aspectRatio: discoverSurface.cardAspectRatio,
    borderRadius: discoverSurface.cardRadius,
    overflow: "hidden",
    backgroundColor: "#0A0A0A",
  },
  pressed: { opacity: 0.94 },
  gradient: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: "58%",
  },
  footer: {
    position: "absolute",
    left: 16,
    right: 10,
    bottom: 14,
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    gap: 8,
  },
  copy: {
    flex: 1,
    paddingRight: 8,
    maxWidth: "82%",
    gap: 3,
  },
  name: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 27,
    lineHeight: 30,
    fontWeight: "400",
  },
  metaLine: {
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    lineHeight: 17,
  },
  metaMuted: {
    color: discoverSurface.metaMuted,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  metaSeparator: {
    color: discoverSurface.metaSeparator,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  metaOpen: {
    color: discoverSurface.open,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  metaClosed: {
    color: discoverSurface.closed,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  crowdRow: {
    marginTop: 2,
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
  },
  crowdIcon: {
    width: 13,
    height: 13,
  },
  crowdText: {
    color: discoverSurface.lime,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 12,
  },
  heartButton: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: -6,
    marginRight: -6,
  },
  heartPressed: { opacity: 0.75 },
  heartIcon: {
    width: 26,
    height: 26,
  },
});
