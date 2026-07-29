import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fontFamilies } from "@/theme";

export function DiscoverEmptyState({
  onShowAll,
  onRefresh,
}: {
  onShowAll: () => void;
  onRefresh: () => void;
}) {
  return (
    <View style={styles.wrap} testID="discover-empty">
      <Text style={styles.title}>Nothing live nearby yet</Text>
      <Text style={styles.body}>Try another category or widen the map area.</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Show all venues"
        onPress={onShowAll}
        style={styles.primary}
      >
        <Text style={styles.primaryText}>Show all venues</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Refresh venues"
        onPress={onRefresh}
        style={styles.secondary}
      >
        <Text style={styles.secondaryText}>Refresh</Text>
      </Pressable>
    </View>
  );
}

export function DiscoverErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={styles.wrap} testID="discover-error">
      <Text style={styles.title}>Couldn’t load venues</Text>
      <Text style={styles.body}>Check your connection and try again.</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Retry loading venues"
        onPress={onRetry}
        style={styles.primary}
      >
        <Text style={styles.primaryText}>Retry</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: 24,
    paddingTop: 40,
    gap: 12,
    alignItems: "center",
  },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
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
    marginTop: 8,
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
});
