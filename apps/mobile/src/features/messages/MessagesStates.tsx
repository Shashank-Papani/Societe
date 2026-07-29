import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fontFamilies } from "@/theme";

export function MessagesErrorState({
  title,
  onRetry,
}: {
  title: string;
  onRetry: () => void;
}) {
  return (
    <View style={styles.wrap} testID="messages-error">
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.body}>Check your connection and try again.</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Retry"
        testID="messages-retry"
        onPress={onRetry}
        style={({ pressed }) => [styles.primary, pressed && styles.pressed]}
      >
        <Text style={styles.primaryText}>Retry</Text>
      </Pressable>
    </View>
  );
}

export function MessagesEmptyState() {
  return (
    <View style={styles.wrap} testID="messages-empty">
      <Text style={styles.title}>No conversations yet</Text>
      <Text style={styles.body}>
        Accept a Calling Card on Connect to start a private chat.
      </Text>
    </View>
  );
}

export function MessagingDisabledState() {
  return (
    <View style={styles.banner} testID="messaging-disabled">
      <Text style={styles.bannerTitle}>Messaging is turned off</Text>
      <Text style={styles.body}>
        Update your privacy settings to send or receive new messages.
      </Text>
    </View>
  );
}

export function ConnectionExpiredState() {
  return (
    <View style={styles.banner} testID="connection-expired">
      <Text style={styles.bannerTitle}>Connection expired</Text>
      <Text style={styles.body}>
        You can no longer send new messages through this connection.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: 8,
    paddingTop: 32,
    gap: 10,
    alignItems: "center",
  },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
    textAlign: "center",
  },
  bannerTitle: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 22,
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
    marginTop: 6,
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
  banner: {
    marginHorizontal: 16,
    marginBottom: 8,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    padding: 14,
    gap: 6,
  },
});
