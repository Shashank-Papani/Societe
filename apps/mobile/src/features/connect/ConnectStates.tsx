import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fontFamilies } from "@/theme";

export function ConnectEmptyPresence({ onGoPresence }: { onGoPresence: () => void }) {
  return (
    <View style={styles.wrap} testID="connect-empty-presence">
      <Text style={styles.title}>Verify your presence first</Text>
      <Text style={styles.body}>
        You need to be at a venue before you can connect with people there.
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Go to Presence"
        testID="connect-go-presence"
        onPress={onGoPresence}
        style={({ pressed }) => [styles.primary, pressed && styles.pressed]}
      >
        <Text style={styles.primaryText}>Go to Presence</Text>
      </Pressable>
    </View>
  );
}

export function ConnectEmptyNearby() {
  return (
    <View style={styles.inline} testID="connect-empty-nearby">
      <Text style={styles.titleSmall}>No one visible here yet</Text>
      <Text style={styles.body}>
        People will appear when they verify at this venue and choose to be discoverable.
      </Text>
    </View>
  );
}

export function ConnectEmptyPending() {
  return (
    <Text style={styles.muted} testID="connect-empty-pending">
      No pending Calling Cards
    </Text>
  );
}

export function ConnectEmptyConnections() {
  return (
    <Text style={styles.muted} testID="connect-empty-connections">
      No connections yet
    </Text>
  );
}

export function ConnectGhostState() {
  return (
    <View style={styles.wrap} testID="connect-ghost">
      <Text style={styles.title}>Ghost Mode is on</Text>
      <Text style={styles.body}>
        Calling Cards are paused until Ghost Mode is off and your presence is verified again.
      </Text>
    </View>
  );
}

export function ConnectErrorState({
  title,
  onRetry,
}: {
  title: string;
  onRetry: () => void;
}) {
  return (
    <View style={styles.inline} testID="connect-error">
      <Text style={styles.titleSmall}>{title}</Text>
      <Text style={styles.body}>Check your connection and try again.</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Retry"
        testID="connect-retry"
        onPress={onRetry}
        style={({ pressed }) => [styles.primary, pressed && styles.pressed]}
      >
        <Text style={styles.primaryText}>Retry</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 20,
    gap: 10,
  },
  inline: { gap: 8, paddingVertical: 8 },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 26,
  },
  titleSmall: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 22,
  },
  body: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    lineHeight: 21,
  },
  muted: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    paddingVertical: 4,
  },
  primary: {
    marginTop: 6,
    alignSelf: "flex-start",
    minHeight: 44,
    paddingHorizontal: 18,
    borderRadius: 999,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 13,
  },
  pressed: { opacity: 0.88 },
});
