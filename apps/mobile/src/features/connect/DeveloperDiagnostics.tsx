import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { QueuedOperation } from "@/features/connect/offlineQueue";
import { colors, fontFamilies } from "@/theme";

type Props = {
  operations: QueuedOperation[];
  presenceState?: string | null;
  socialEligible?: boolean;
  ghostOn?: boolean;
};

/**
 * Development-only raw queue / presence diagnostics.
 * Must not render meaningful content in production builds.
 */
export function DeveloperDiagnostics({
  operations,
  presenceState,
  socialEligible,
  ghostOn,
}: Props) {
  const [open, setOpen] = useState(false);

  if (!__DEV__) {
    return null;
  }

  return (
    <View style={styles.wrap} testID="connect-dev-diagnostics">
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Developer diagnostics"
        onPress={() => setOpen((value) => !value)}
        style={styles.header}
      >
        <Text style={styles.title}>Developer diagnostics</Text>
        <Text style={styles.chevron}>{open ? "▾" : "▸"}</Text>
      </Pressable>
      {open ? (
        <View style={styles.body}>
          <Text style={styles.row}>presence_state · {presenceState ?? "—"}</Text>
          <Text style={styles.row}>
            social_features_enabled · {socialEligible ? "true" : "false"}
          </Text>
          <Text style={styles.row}>ghost_mode · {ghostOn ? "true" : "false"}</Text>
          {operations.length === 0 ? (
            <Text style={styles.row}>queue · empty</Text>
          ) : (
            operations.map((op) => (
              <View key={op.id} style={styles.op}>
                <Text style={styles.row}>{op.operationType}</Text>
                <Text style={styles.meta}>
                  state · {op.state} · attempts · {op.attempts}
                </Text>
                {op.lastErrorCode ? (
                  <Text style={styles.meta}>lastError · {op.lastErrorCode}</Text>
                ) : null}
                <Text style={styles.meta}>queued · {op.createdAt}</Text>
              </View>
            ))
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: "rgba(10, 21, 15, 0.45)",
    overflow: "hidden",
  },
  header: {
    minHeight: 44,
    paddingHorizontal: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
    letterSpacing: 0.4,
  },
  chevron: { color: colors.textSecondary, fontSize: 14 },
  body: { paddingHorizontal: 14, paddingBottom: 12, gap: 6 },
  row: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 11,
  },
  meta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 10,
    opacity: 0.85,
  },
  op: {
    gap: 2,
    paddingVertical: 6,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
});
