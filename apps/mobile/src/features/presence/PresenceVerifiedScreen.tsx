import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  formatClock,
  formatMethodLabel,
  formatVisibilityLabel,
} from "@/features/venue/venuePresentation";
import { colors, fontFamilies } from "@/theme";

export type PresenceVerifiedProps = {
  venueName: string;
  venueId: string;
  verifiedAtIso?: string | null;
  expiresAtIso?: string | null;
  verificationLevel?: string | null;
  ghostMode?: boolean;
  discoverableInVenue?: boolean;
  socialFeaturesEnabled?: boolean;
  timeZone?: string;
  showBackToVenue?: boolean;
  onSeeWhosHere?: () => void;
  onBackToVenue?: () => void;
  onViewLiveVibes?: () => void;
};

function Detail({
  label,
  value,
  right,
}: {
  label: string;
  value: string;
  right?: boolean;
}) {
  return (
    <View style={[styles.detail, right && styles.detailRight]} accessibilityLabel={`${label}: ${value}`}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

export function PresenceVerifiedScreen({
  venueName,
  venueId,
  verifiedAtIso,
  expiresAtIso,
  verificationLevel,
  ghostMode,
  discoverableInVenue,
  socialFeaturesEnabled,
  timeZone,
  showBackToVenue = true,
  onSeeWhosHere,
  onBackToVenue,
  onViewLiveVibes,
}: PresenceVerifiedProps) {
  const router = useRouter();
  const visibility = formatVisibilityLabel({
    ghostMode,
    discoverableInVenue,
    socialFeaturesEnabled,
  });

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom", "left", "right"]} testID="presence-verified">
      <View style={styles.container}>
        <View
          style={styles.successMark}
          accessibilityRole="image"
          accessibilityLabel="Presence verified"
        >
          <Text style={styles.check}>✓</Text>
        </View>
        <Text style={styles.title} accessibilityRole="header">
          Presence Verified
        </Text>
        <Text style={styles.subtitle} accessibilityLiveRegion="polite">
          You’re now verified at this venue and visible according to your privacy settings.
        </Text>

        <LinearGradient
          colors={["#07150e", "#030a06"]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.card}
        >
          <Text style={styles.venueName} numberOfLines={2}>
            {venueName}
          </Text>
          <Text style={styles.statusChip}>VERIFIED</Text>

          <View style={styles.detailGrid}>
            <Detail label="VENUE" value={venueName} />
            <Detail
              label="VERIFIED"
              value={formatClock(verifiedAtIso, timeZone)}
              right
            />
            <Detail label="EXPIRES" value={formatClock(expiresAtIso, timeZone)} />
            <Detail label="VISIBILITY" value={visibility} right />
            <Detail label="METHOD" value={formatMethodLabel(verificationLevel)} />
          </View>
        </LinearGradient>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="See who’s here"
          testID="presence-see-whos-here"
          onPress={() => {
            if (onSeeWhosHere) {
              onSeeWhosHere();
              return;
            }
            router.push("/(tabs)/connect");
          }}
          style={({ pressed }) => [styles.primary, pressed && styles.pressed]}
        >
          <Text style={styles.primaryText}>SEE WHO’S HERE</Text>
        </Pressable>

        {onViewLiveVibes ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="View Live Vibes"
            onPress={onViewLiveVibes}
            style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}
          >
            <Text style={styles.secondaryText}>VIEW LIVE VIBES</Text>
          </Pressable>
        ) : null}

        {showBackToVenue ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Back to venue"
            testID="presence-back-to-venue"
            onPress={() => {
              if (onBackToVenue) {
                onBackToVenue();
                return;
              }
              router.replace(`/venue/${venueId}`);
            }}
            style={({ pressed }) => [styles.tertiary, pressed && styles.pressed]}
          >
            <Text style={styles.tertiaryText}>BACK TO VENUE</Text>
          </Pressable>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: {
    flex: 1,
    alignItems: "center",
    paddingHorizontal: 24,
    paddingTop: 28,
    paddingBottom: 16,
  },
  successMark: {
    width: 72,
    height: 72,
    borderRadius: 36,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.lime,
    shadowColor: colors.lime,
    shadowOpacity: 0.5,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
  check: {
    color: colors.limeInk,
    fontSize: 34,
    fontFamily: fontFamilies.geistBold,
    lineHeight: 38,
  },
  title: {
    marginTop: 22,
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 34,
    textAlign: "center",
  },
  subtitle: {
    marginTop: 10,
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    lineHeight: 21,
    textAlign: "center",
    maxWidth: 320,
  },
  card: {
    marginTop: 28,
    width: "100%",
    borderRadius: 22,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 20,
    gap: 14,
  },
  venueName: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
  },
  statusChip: {
    alignSelf: "flex-start",
    color: colors.lime,
    fontFamily: fontFamilies.geistBold,
    fontSize: 12,
    letterSpacing: 1.2,
  },
  detailGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    rowGap: 16,
    columnGap: 12,
  },
  detail: { width: "47%" },
  detailRight: { alignItems: "flex-end" },
  detailLabel: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 11,
    letterSpacing: 1,
    marginBottom: 4,
  },
  detailValue: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 15,
    textAlign: "left",
  },
  primary: {
    marginTop: 24,
    width: "100%",
    minHeight: 56,
    borderRadius: 28,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 15,
  },
  secondary: {
    marginTop: 12,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 13,
    letterSpacing: 0.6,
  },
  tertiary: {
    marginTop: 4,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  tertiaryText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
    letterSpacing: 0.5,
  },
  pressed: { opacity: 0.88 },
});
