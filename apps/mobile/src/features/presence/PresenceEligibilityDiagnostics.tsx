import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import {
  DEV_PRESENCE_TEST_LOCATION,
  type PresenceEligibilityView,
} from "@/features/presence/presenceEligibility";
import { fontFamilies } from "@/theme";

type Props = {
  eligibility: PresenceEligibilityView | null;
  venueLatitude?: number | null;
  venueLongitude?: number | null;
  useDevFixture: boolean;
  onToggleDevFixture: () => void;
  onRefresh: () => void;
};

/**
 * Collapsed __DEV__ panel for Presence location / eligibility diagnostics.
 * Must not render in production builds.
 */
export function PresenceEligibilityDiagnostics({
  eligibility,
  venueLatitude,
  venueLongitude,
  useDevFixture,
  onToggleDevFixture,
  onRefresh,
}: Props) {
  const [open, setOpen] = useState(false);

  if (!__DEV__) {
    return null;
  }

  return (
    <View style={styles.wrap} testID="presence-eligibility-diagnostics">
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Presence location diagnostics"
        onPress={() => setOpen((value) => !value)}
        style={styles.header}
      >
        <Text style={styles.title}>Location diagnostics</Text>
        <Text style={styles.chevron}>{open ? "▾" : "▸"}</Text>
      </Pressable>
      {open ? (
        <View style={styles.body}>
          <Text style={styles.row}>
            user · {eligibility?.userLatitude ?? "—"}, {eligibility?.userLongitude ?? "—"}
          </Text>
          <Text style={styles.row}>
            venue · {venueLatitude ?? "—"}, {venueLongitude ?? "—"}
          </Text>
          <Text style={styles.row}>
            distance_meters · {eligibility?.distanceMeters ?? "—"}
          </Text>
          <Text style={styles.row}>
            allowed_radius_meters · {eligibility?.allowedRadiusMeters ?? "—"}
          </Text>
          <Text style={styles.row}>
            location_accuracy_meters · {eligibility?.locationAccuracyMeters ?? "—"}
          </Text>
          <Text style={styles.row}>reason · {eligibility?.reason ?? "—"}</Text>
          <Text style={styles.row}>observed_at · {eligibility?.observedAt ?? "—"}</Text>
          <Text style={styles.row}>
            fixture · {DEV_PRESENCE_TEST_LOCATION.label} ({useDevFixture ? "on" : "off"})
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={
              useDevFixture ? "Disable development location fixture" : "Enable development location fixture"
            }
            testID="presence-dev-fixture-toggle"
            onPress={onToggleDevFixture}
            style={styles.action}
          >
            <Text style={styles.actionText}>
              {useDevFixture
                ? "Cycle fixture (30m → 200m → 300m → off)"
                : "Use dev fixture (~30m)"}
            </Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Refresh eligibility"
            testID="presence-eligibility-refresh"
            onPress={onRefresh}
            style={styles.action}
          >
            <Text style={styles.actionText}>Refresh location</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: 12,
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(255,255,255,0.12)",
    backgroundColor: "#0A0A0A",
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
    color: "rgba(255,255,255,0.55)",
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
  },
  chevron: {
    color: "rgba(255,255,255,0.4)",
    fontSize: 12,
  },
  body: {
    paddingHorizontal: 14,
    paddingBottom: 12,
    gap: 4,
  },
  row: {
    color: "rgba(255,255,255,0.45)",
    fontFamily: fontFamilies.geistRegular,
    fontSize: 11,
  },
  action: {
    marginTop: 8,
    minHeight: 40,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.12)",
    alignItems: "center",
    justifyContent: "center",
  },
  actionText: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 12,
  },
});
