import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, fontFamilies, spacing } from "@/theme";

type Props = {
  title: string;
  subtitle?: string | null;
  eyebrow?: string | null;
  right?: ReactNode;
  testID?: string;
};

export function NoirHeader({ title, subtitle, eyebrow, right, testID }: Props) {
  return (
    <View style={styles.row} testID={testID}>
      <View style={styles.copy}>
        {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
        {subtitle ? (
          <Text style={styles.subtitle} numberOfLines={2}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      {right ? <View style={styles.right}>{right}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  copy: { flex: 1, gap: 4 },
  eyebrow: {
    color: colors.gold,
    fontFamily: fontFamilies.geistBold,
    fontSize: 11,
    letterSpacing: 1.4,
  },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 36,
  },
  subtitle: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  right: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
});
