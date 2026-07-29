import { ComponentProps, ReactNode } from "react";
import {
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, fonts } from "./theme";

type IconName = ComponentProps<typeof Ionicons>["name"];

export function CircleButton({
  icon,
  onPress,
  filled = false,
}: {
  icon: IconName;
  onPress?: () => void;
  filled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [
        styles.circleButton,
        filled && styles.circleButtonFilled,
        pressed && styles.pressed,
      ]}
    >
      <Ionicons name={icon} size={18} color={filled ? colors.black : colors.white} />
    </Pressable>
  );
}

export function Eyebrow({ children, gold = false }: { children: ReactNode; gold?: boolean }) {
  return <Text style={[styles.eyebrow, gold && styles.eyebrowGold]}>{children}</Text>;
}

export function NeonButton({
  label,
  onPress,
  icon,
  compact = false,
  style,
}: {
  label: string;
  onPress?: () => void;
  icon?: IconName;
  compact?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [
        styles.neonButton,
        compact && styles.neonButtonCompact,
        style,
        pressed && styles.pressed,
      ]}
    >
      {icon ? <Ionicons name={icon} size={16} color={colors.black} /> : null}
      <Text style={styles.neonButtonText}>{label}</Text>
    </Pressable>
  );
}

export function BottomNav({
  active,
  onDiscover,
}: {
  active: "discover" | "messages" | "saved" | "passes";
  onDiscover: () => void;
}) {
  const items: { key: typeof active; icon: IconName; activeIcon: IconName; onPress?: () => void }[] =
    [
      { key: "discover", icon: "options-outline", activeIcon: "options", onPress: onDiscover },
      { key: "messages", icon: "chatbubble-outline", activeIcon: "chatbubble" },
      { key: "saved", icon: "bookmark-outline", activeIcon: "bookmark" },
      { key: "passes", icon: "ticket-outline", activeIcon: "ticket" },
    ];

  return (
    <View style={styles.nav}>
      {items.map((item) => {
        const selected = active === item.key;
        return (
          <Pressable
            accessibilityRole="button"
            key={item.key}
            onPress={item.onPress}
            style={({ pressed }) => [
              styles.navButton,
              selected && styles.navButtonActive,
              pressed && styles.pressed,
            ]}
          >
            <Ionicons
              name={selected ? item.activeIcon : item.icon}
              size={20}
              color={selected ? colors.black : colors.mutedLight}
            />
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  circleButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.15)",
    backgroundColor: "rgba(0,0,0,0.42)",
  },
  circleButtonFilled: {
    backgroundColor: colors.lime,
    borderColor: colors.lime,
  },
  pressed: {
    opacity: 0.72,
    transform: [{ scale: 0.98 }],
  },
  eyebrow: {
    color: colors.lime,
    fontFamily: fonts.sansHeavy,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.1,
    textTransform: "uppercase",
  },
  eyebrowGold: {
    color: colors.gold,
  },
  neonButton: {
    minHeight: 52,
    paddingHorizontal: 24,
    borderRadius: 999,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.lime,
    shadowColor: colors.lime,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.42,
    shadowRadius: 15,
    elevation: 8,
  },
  neonButtonCompact: {
    minHeight: 44,
    paddingHorizontal: 22,
  },
  neonButtonText: {
    color: colors.black,
    fontFamily: fonts.sansHeavy,
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 0.2,
    textTransform: "uppercase",
  },
  nav: {
    height: 72,
    paddingHorizontal: 30,
    paddingTop: 12,
    paddingBottom: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    backgroundColor: "#020906",
  },
  navButton: {
    width: 42,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 21,
  },
  navButtonActive: {
    backgroundColor: colors.lime,
    shadowColor: colors.lime,
    shadowOpacity: 0.35,
    shadowRadius: 8,
  },
});
