import { Pressable, StyleSheet, Text, View } from "react-native";

import type { CallingCardSummary } from "@/features/connect/api";
import {
  formatConnectionAvailable,
  formatRelativeTime,
  friendlyCardStatusLabel,
} from "@/features/connect/connectPresentation";
import { ProfileAvatar } from "@/features/connect/ProfileAvatar";
import { reasonCodeLabel } from "@/features/connect/queueHelpers";
import { colors, fontFamilies } from "@/theme";

type Props = {
  card: CallingCardSummary;
  nowMs: number;
  title: string;
  subtitle?: string | null;
  handle?: string | null;
  queueHint?: string | null;
  showConnectionExpiry?: boolean;
  onAccept?: () => void;
  onDecline?: () => void;
  onMessage?: () => void;
  onCancel?: () => void;
  onBlock?: () => void;
  onRetry?: () => void;
  busy?: boolean;
};

export function CallingCardRow({
  card,
  nowMs,
  title,
  subtitle,
  handle,
  queueHint,
  showConnectionExpiry,
  onAccept,
  onDecline,
  onMessage,
  onCancel,
  onBlock,
  onRetry,
  busy,
}: Props) {
  const status = friendlyCardStatusLabel(card.status);
  const age = formatRelativeTime(card.created_at, nowMs);
  const connectionLeft =
    showConnectionExpiry && card.status === "accepted"
      ? formatConnectionAvailable(card.expires_at, nowMs)
      : null;
  const reason = card.reason_code ? reasonCodeLabel(card.reason_code) : null;
  const customMessage =
    (card.custom_message ?? card.reason_text)?.trim() || null;
  const showMessage = Boolean(customMessage) && card.status !== "accepted";

  return (
    <View style={styles.card} testID={`calling-card-${card.id}`}>
      <View style={styles.row}>
        <ProfileAvatar displayName={title} handle={handle} size={48} />
        <View style={styles.copy}>
          <Text style={styles.name} numberOfLines={1}>
            {title}
          </Text>
          {subtitle ? (
            <Text style={styles.meta} numberOfLines={1}>
              {subtitle}
            </Text>
          ) : null}
          <Text style={styles.statusRow}>
            <Text
              style={[
                styles.status,
                card.status === "accepted" && styles.statusGold,
              ]}
            >
              {status}
            </Text>
            {age ? <Text style={styles.meta}> · {age}</Text> : null}
          </Text>
          {reason && card.status !== "accepted" ? (
            <Text style={styles.reason} testID={`calling-card-reason-${card.id}`}>
              {reason}
            </Text>
          ) : null}
          {showMessage ? (
            <Text style={styles.message} testID={`calling-card-message-${card.id}`}>
              {customMessage}
            </Text>
          ) : null}
          {connectionLeft ? (
            <Text style={styles.connection}>{connectionLeft}</Text>
          ) : null}
          {queueHint ? (
            <Text style={styles.queueHint} accessibilityLiveRegion="polite">
              {queueHint}
            </Text>
          ) : null}
        </View>
      </View>

      <View style={styles.actions}>
        {onAccept ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Accept Calling Card"
            testID={`calling-card-accept-${card.id}`}
            disabled={busy}
            onPress={onAccept}
            style={({ pressed }) => [styles.primary, busy && styles.disabled, pressed && styles.pressed]}
          >
            <Text style={styles.primaryText}>Accept</Text>
          </Pressable>
        ) : null}
        {onDecline ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Decline Calling Card"
            testID={`calling-card-decline-${card.id}`}
            disabled={busy}
            onPress={onDecline}
            style={({ pressed }) => [styles.secondary, busy && styles.disabled, pressed && styles.pressed]}
          >
            <Text style={styles.secondaryText}>Decline</Text>
          </Pressable>
        ) : null}
        {onMessage ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Message"
            testID={`calling-card-message-${card.id}`}
            disabled={busy}
            onPress={onMessage}
            style={({ pressed }) => [styles.primary, busy && styles.disabled, pressed && styles.pressed]}
          >
            <Text style={styles.primaryText}>Message</Text>
          </Pressable>
        ) : null}
        {onCancel ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Cancel Calling Card"
            testID={`calling-card-cancel-${card.id}`}
            disabled={busy}
            onPress={onCancel}
            style={({ pressed }) => [styles.secondary, busy && styles.disabled, pressed && styles.pressed]}
          >
            <Text style={styles.secondaryText}>Cancel</Text>
          </Pressable>
        ) : null}
        {onRetry ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Try again"
            disabled={busy}
            onPress={onRetry}
            style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}
          >
            <Text style={styles.secondaryText}>Try Again</Text>
          </Pressable>
        ) : null}
        {onBlock ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Block"
            onPress={onBlock}
            hitSlop={8}
            style={styles.blockBtn}
          >
            <Text style={styles.blockText}>Block</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 16,
    gap: 12,
  },
  row: { flexDirection: "row", gap: 12 },
  copy: { flex: 1, gap: 2 },
  name: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 22,
  },
  meta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  statusRow: { marginTop: 2 },
  status: {
    color: colors.lime,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 12,
  },
  statusGold: { color: colors.gold },
  reason: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
    marginTop: 4,
  },
  message: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    marginTop: 2,
    lineHeight: 18,
  },
  connection: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
    marginTop: 2,
  },
  queueHint: {
    color: colors.gold,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
    marginTop: 2,
  },
  actions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    alignItems: "center",
  },
  primary: {
    minHeight: 44,
    paddingHorizontal: 16,
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
  secondary: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.surfaceTranslucent,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 13,
  },
  blockBtn: { minHeight: 44, justifyContent: "center", paddingHorizontal: 4 },
  blockText: {
    color: colors.danger,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  disabled: { opacity: 0.65 },
  pressed: { opacity: 0.9 },
});
