import { Pressable, StyleSheet, Text } from "react-native";

import { colors, fontFamilies, radii, spacing } from "@/theme";

type Props = {
  label: string;
  selected?: boolean;
  onPress?: () => void;
  testID?: string;
};

export function NoirPill({ label, selected, onPress, testID }: Props) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: Boolean(selected) }}
      accessibilityLabel={label}
      testID={testID}
      onPress={onPress}
      style={[styles.pill, selected && styles.selected]}
    >
      <Text style={[styles.text, selected && styles.textSelected]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pill: {
    minHeight: 36,
    paddingHorizontal: spacing.sm,
    borderRadius: radii.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderSubtle,
    backgroundColor: colors.surfaceSolid,
    alignItems: "center",
    justifyContent: "center",
  },
  selected: {
    backgroundColor: colors.neon,
    borderColor: colors.neon,
  },
  text: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 12,
  },
  textSelected: { color: colors.neonText },
});
