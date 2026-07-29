import { Pressable, StyleSheet, Text, View } from "react-native";

import type { DiscoverableUser } from "@/features/connect/api";
import { nearbyPersonAccessibilityLabel } from "@/features/connect/connectPresentation";
import { ProfileAvatar } from "@/features/connect/ProfileAvatar";
import { colors, fontFamilies } from "@/theme";

type Props = {
  person: DiscoverableUser;
  venueName: string | null;
  selected?: boolean;
  actionLabel: string | null;
  actionPending?: boolean;
  statusHint?: string | null;
  onSelect?: () => void;
  onPrimaryAction?: () => void;
  onBlock: () => void;
};

export function NearbyPersonCard({
  person,
  venueName,
  selected,
  actionLabel,
  actionPending,
  statusHint,
  onSelect,
  onPrimaryAction,
  onBlock,
}: Props) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={nearbyPersonAccessibilityLabel(person)}
      accessibilityState={{ selected: Boolean(selected) }}
      testID={`nearby-person-${person.user_id}`}
      onPress={onSelect}
      style={({ pressed }) => [
        styles.card,
        selected && styles.cardSelected,
        pressed && styles.pressed,
      ]}
    >
      <View style={styles.row}>
        <View style={styles.avatarWrap}>
          <ProfileAvatar displayName={person.display_name} handle={person.handle} />
          <View style={styles.presenceDot} accessibilityLabel="Present at venue" />
        </View>
        <View style={styles.copy}>
          <Text style={styles.name} numberOfLines={1}>
            {person.display_name}
          </Text>
          <Text style={styles.handle} numberOfLines={1}>
            @{person.handle}
          </Text>
          {venueName ? (
            <Text style={styles.context} numberOfLines={1}>
              At {venueName}
            </Text>
          ) : null}
          {statusHint ? (
            <Text style={styles.statusHint} accessibilityLiveRegion="polite">
              {statusHint}
            </Text>
          ) : null}
        </View>
      </View>

      <View style={styles.actions}>
        {actionLabel && onPrimaryAction ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={actionLabel}
            accessibilityState={{ disabled: Boolean(actionPending) }}
            testID={`nearby-send-${person.user_id}`}
            disabled={actionPending}
            onPress={onPrimaryAction}
            style={({ pressed }) => [
              styles.primary,
              actionPending && styles.disabled,
              pressed && styles.pressed,
            ]}
          >
            <Text style={styles.primaryText}>
              {actionPending ? "Sending…" : actionLabel}
            </Text>
          </Pressable>
        ) : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Block ${person.display_name}`}
          testID={`nearby-block-${person.user_id}`}
          onPress={onBlock}
          hitSlop={8}
          style={styles.blockBtn}
        >
          <Text style={styles.blockText}>Block</Text>
        </Pressable>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 16,
    gap: 14,
  },
  cardSelected: {
    borderColor: "rgba(185, 249, 8, 0.35)",
  },
  pressed: { opacity: 0.9 },
  row: { flexDirection: "row", gap: 12, alignItems: "center" },
  avatarWrap: { position: "relative" },
  presenceDot: {
    position: "absolute",
    right: 0,
    bottom: 0,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.lime,
    borderWidth: 2,
    borderColor: colors.surface,
  },
  copy: { flex: 1, gap: 2 },
  name: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 22,
  },
  handle: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  context: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
    marginTop: 2,
  },
  statusHint: {
    color: colors.gold,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
    marginTop: 4,
  },
  actions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  primary: {
    flex: 1,
    minHeight: 44,
    borderRadius: 999,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 14,
  },
  primaryText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 13,
  },
  disabled: { opacity: 0.65 },
  blockBtn: {
    minHeight: 44,
    justifyContent: "center",
    paddingHorizontal: 4,
  },
  blockText: {
    color: colors.danger,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
});
