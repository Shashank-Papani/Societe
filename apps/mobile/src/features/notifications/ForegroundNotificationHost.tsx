import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ProfileAvatar } from "@/features/connect/ProfileAvatar";
import { reasonCodeLabel } from "@/features/connect/queueHelpers";
import {
  useForegroundNotifications,
  type ForegroundNotification,
} from "@/features/notifications/ForegroundNotificationProvider";
import { colors, fontFamilies, radii, spacing } from "@/theme";

/**
 * Root-level host for Calling Card drawers and message banners.
 * Mount once near the app root — do not duplicate per tab.
 */
export function ForegroundNotificationHost() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { active, dismiss, respondCallingCard } = useForegroundNotifications();
  const [responding, setResponding] = useState(false);

  useEffect(() => {
    if (!active || active.kind !== "message") {
      return;
    }
    const timer = setTimeout(() => dismiss(active.id), 5000);
    return () => clearTimeout(timer);
  }, [active, dismiss]);

  const callingCard = active?.kind === "calling_card" ? active : null;
  const message = active?.kind === "message" ? active : null;
  const reason = callingCard?.reasonCode
    ? reasonCodeLabel(callingCard.reasonCode)
    : null;

  if (callingCard) {
    return (
      <View
        style={[styles.drawerWrap, { paddingBottom: insets.bottom + 12 }]}
        testID="foreground-calling-card-drawer"
        accessibilityLiveRegion="polite"
      >
        <View style={styles.drawer}>
          <View style={styles.handle} />
          <View style={styles.drawerHeader}>
            <ProfileAvatar
              displayName={callingCard.displayName}
              handle={callingCard.handle}
              photoUrl={callingCard.avatarUrl}
              size={52}
            />
            <View style={styles.drawerCopy}>
              <Text style={styles.name}>{callingCard.displayName}</Text>
              {callingCard.handle ? (
                <Text style={styles.handleText}>@{callingCard.handle}</Text>
              ) : null}
              {callingCard.venueName ? (
                <Text style={styles.meta}>{callingCard.venueName}</Text>
              ) : null}
            </View>
          </View>
          {reason ? <Text style={styles.reason}>{reason}</Text> : null}
          {callingCard.customMessage ? (
            <Text style={styles.message}>{callingCard.customMessage}</Text>
          ) : null}
          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Decline Calling Card"
              disabled={responding}
              testID="foreground-calling-card-decline"
              onPress={() => {
                setResponding(true);
                void respondCallingCard(callingCard.callingCardId, "decline").finally(() =>
                  setResponding(false),
                );
              }}
              style={styles.secondary}
            >
              <Text style={styles.secondaryText}>Decline</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Accept Calling Card"
              disabled={responding}
              testID="foreground-calling-card-accept"
              onPress={() => {
                setResponding(true);
                void respondCallingCard(callingCard.callingCardId, "accept").finally(() =>
                  setResponding(false),
                );
              }}
              style={styles.primary}
            >
              <Text style={styles.primaryText}>Accept</Text>
            </Pressable>
          </View>
        </View>
      </View>
    );
  }

  if (message) {
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Message from ${message.displayName}`}
        testID="foreground-message-banner"
        onPress={() => {
          dismiss(message.id);
          router.push(`/messages/${message.conversationId}`);
        }}
        style={[styles.banner, { top: insets.top + 8 }]}
      >
        <ProfileAvatar
          displayName={message.displayName}
          handle={message.handle}
          photoUrl={message.avatarUrl}
          size={40}
        />
        <View style={styles.bannerCopy}>
          <Text style={styles.bannerName}>{message.displayName}</Text>
          <Text style={styles.bannerPreview} numberOfLines={1}>
            {message.previewHidden ? "New message" : message.preview}
          </Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Dismiss"
          onPress={() => dismiss(message.id)}
          hitSlop={8}
        >
          <Text style={styles.dismiss}>✕</Text>
        </Pressable>
      </Pressable>
    );
  }

  return null;
}

/** Type re-export for tests. */
export type { ForegroundNotification };

const styles = StyleSheet.create({
  drawerWrap: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.overlayDark,
    justifyContent: "flex-end",
  },
  drawer: {
    backgroundColor: colors.surfaceElevated,
    borderTopLeftRadius: radii.modal,
    borderTopRightRadius: radii.modal,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderSubtle,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    gap: spacing.sm,
  },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: "rgba(255,255,255,0.16)",
    marginBottom: 4,
  },
  drawerHeader: { flexDirection: "row", gap: 12, alignItems: "center" },
  drawerCopy: { flex: 1, gap: 2 },
  name: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 24,
  },
  handleText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  meta: {
    color: colors.textTertiary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  reason: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 15,
  },
  message: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    lineHeight: 20,
  },
  actions: { flexDirection: "row", gap: 10, marginTop: 4 },
  secondary: {
    flex: 1,
    minHeight: 48,
    borderRadius: radii.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderMedium,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 14,
  },
  primary: {
    flex: 1,
    minHeight: 48,
    borderRadius: radii.pill,
    backgroundColor: colors.neon,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: {
    color: colors.neonText,
    fontFamily: fontFamilies.geistBold,
    fontSize: 14,
  },
  banner: {
    position: "absolute",
    left: 12,
    right: 12,
    minHeight: 64,
    borderRadius: radii.large,
    backgroundColor: colors.surfaceGlass,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderMedium,
    paddingHorizontal: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    zIndex: 50,
  },
  bannerCopy: { flex: 1, gap: 2 },
  bannerName: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 14,
  },
  bannerPreview: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  dismiss: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 16,
    padding: 8,
  },
});
