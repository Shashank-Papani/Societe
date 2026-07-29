import { Pressable, StyleSheet, Text, type PressableProps } from "react-native";

import { colors, fontFamilies, motion, radii, spacing } from "@/theme";

type Variant = "primary" | "secondary" | "ghost" | "danger";

type Props = PressableProps & {
  label: string;
  variant?: Variant;
  testID?: string;
};

export function NoirButton({
  label,
  variant = "primary",
  disabled,
  testID,
  style,
  ...rest
}: Props) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: Boolean(disabled) }}
      disabled={disabled}
      testID={testID}
      style={(state) => [
        styles.base,
        variant === "primary" && styles.primary,
        variant === "secondary" && styles.secondary,
        variant === "ghost" && styles.ghost,
        variant === "danger" && styles.danger,
        disabled && styles.disabled,
        state.pressed && !disabled && { transform: [{ scale: motion.pressScale }] },
        typeof style === "function" ? style(state) : style,
      ]}
      {...rest}
    >
      <Text
        style={[
          styles.label,
          variant === "primary" && styles.labelOnNeon,
          variant === "danger" && styles.labelDanger,
          (variant === "secondary" || variant === "ghost") && styles.labelLight,
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 48,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
    justifyContent: "center",
  },
  primary: { backgroundColor: colors.neon },
  secondary: {
    backgroundColor: colors.surfaceElevated,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderMedium,
  },
  ghost: { backgroundColor: "transparent" },
  danger: {
    backgroundColor: "rgba(255, 107, 107, 0.14)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(255, 107, 107, 0.35)",
  },
  disabled: { opacity: 0.5 },
  label: { fontFamily: fontFamilies.geistBold, fontSize: 14 },
  labelOnNeon: { color: colors.neonText },
  labelLight: { color: colors.textPrimary },
  labelDanger: { color: colors.danger },
});
