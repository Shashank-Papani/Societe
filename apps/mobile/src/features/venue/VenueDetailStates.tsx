import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fontFamilies } from "@/theme";

export function VenueDetailErrorState({
  onRetry,
  onBack,
}: {
  onRetry: () => void;
  onBack: () => void;
}) {
  return (
    <View style={styles.wrap} testID="venue-detail-error">
      <Text style={styles.title} accessibilityRole="header">
        Couldn’t load this venue
      </Text>
      <Text style={styles.body}>Check your connection and try again.</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Retry loading venue"
        testID="venue-detail-retry"
        onPress={onRetry}
        style={({ pressed }) => [styles.primary, pressed && styles.pressed]}
      >
        <Text style={styles.primaryText}>Retry</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Back to Discover"
        testID="venue-detail-back-discover"
        onPress={onBack}
        style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}
      >
        <Text style={styles.secondaryText}>Back to Discover</Text>
      </Pressable>
    </View>
  );
}

export function VenueDetailMissingState({ onBack }: { onBack: () => void }) {
  return (
    <View style={styles.wrap} testID="venue-detail-missing">
      <Text style={styles.title} accessibilityRole="header">
        Venue unavailable
      </Text>
      <Text style={styles.body}>
        This venue may have been removed or is no longer available.
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Back to Discover"
        testID="venue-detail-missing-back"
        onPress={onBack}
        style={({ pressed }) => [styles.primary, pressed && styles.pressed]}
      >
        <Text style={styles.primaryText}>Back to Discover</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: colors.background,
    paddingHorizontal: 24,
    paddingTop: 80,
    gap: 12,
    alignItems: "center",
  },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 30,
    textAlign: "center",
  },
  body: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    lineHeight: 21,
    textAlign: "center",
    maxWidth: 300,
  },
  primary: {
    marginTop: 10,
    minHeight: 48,
    paddingHorizontal: 22,
    borderRadius: 999,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 14,
  },
  secondary: {
    minHeight: 44,
    paddingHorizontal: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  pressed: { opacity: 0.88 },
});
