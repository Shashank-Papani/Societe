/**
 * Lightweight informational surface for claim / invitation deep links
 * (Phase 7B management UI is deferred).
 */

import { useLocalSearchParams, useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, fontFamilies, spacing } from "@/theme";

export function NotificationInfoScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ kind?: string }>();
  const kind = typeof params.kind === "string" ? params.kind : "";

  const copy =
    kind === "venue_claim"
      ? {
          title: "Venue claim update",
          body: "Your venue claim status was updated. Full venue management tools arrive in a later release.",
        }
      : kind === "organization_invitation"
        ? {
            title: "Organization invitation",
            body: "You have an organization invitation. Acceptance and management tools arrive in a later release.",
          }
        : {
            title: "Notification",
            body: "This notification destination is not available yet.",
          };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          onPress={() => router.back()}
        >
          <Text style={styles.backText}>Back</Text>
        </Pressable>
      </View>
      <View style={styles.body}>
        <Text style={styles.title} accessibilityRole="header">
          {copy.title}
        </Text>
        <Text style={styles.text}>{copy.body}</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  backText: { color: colors.neon, fontFamily: fontFamilies.geistMedium, fontSize: 15 },
  body: { padding: spacing.lg, gap: 12 },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 32,
  },
  text: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
    lineHeight: 22,
  },
});
