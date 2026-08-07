/**
 * Header bell + unread badge for Discover (and reusable elsewhere).
 */

import { Image } from "expo-image";
import { useRouter, type Href } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { noirIcons } from "@/icons/noirIcons";
import { colors, fontFamilies } from "@/theme";
import {
  formatUnreadBadge,
  unreadBadgeAccessibilityLabel,
} from "./notificationHelpers";
import { useNotificationsOptional } from "./NotificationsProvider";

type Props = {
  testID?: string;
};

export function NotificationBellButton({ testID = "notification-bell" }: Props) {
  const router = useRouter();
  const notifications = useNotificationsOptional();
  const total = notifications?.unreadTotal ?? 0;
  const badge = formatUnreadBadge(total);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={unreadBadgeAccessibilityLabel(total)}
      testID={testID}
      onPress={() => router.push("/notifications" as Href)}
      style={({ pressed }) => [styles.button, pressed && styles.pressed]}
    >
      <Image
        source={noirIcons.notificationsWhite}
        style={styles.icon}
        contentFit="contain"
        accessibilityIgnoresInvertColors
      />
      {badge ? (
        <View style={styles.badge} testID={`${testID}-badge`}>
          <Text style={styles.badgeText} accessibilityElementsHidden>
            {badge}
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#080808",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.06)",
  },
  icon: { width: 21, height: 21 },
  badge: {
    position: "absolute",
    top: 4,
    right: 2,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    paddingHorizontal: 4,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.neon,
  },
  badgeText: {
    color: colors.neonText,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 10,
    lineHeight: 12,
  },
  pressed: { opacity: 0.85 },
});
