/**
 * Notification preferences — in-app + push toggles per category.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "@/api/client";
import { colors, fontFamilies, spacing } from "@/theme";
import { fetchNotificationPreferences, patchNotificationPreferences } from "./api";
import {
  categoryLabel,
  isKnownCategory,
  isMandatoryInAppCategory,
} from "./notificationHelpers";
import {
  getPushPermissionState,
  registerCurrentDevicePushToken,
  requestPushPermission,
  unregisterCurrentDevicePushToken,
} from "./pushRegistration";

export function NotificationPreferencesScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [permissionHint, setPermissionHint] = useState<string | null>(null);
  const [savingCategory, setSavingCategory] = useState<string | null>(null);

  const prefsQuery = useQuery({
    queryKey: ["notifications", "preferences"],
    queryFn: fetchNotificationPreferences,
  });

  const patchMutation = useMutation({
    mutationFn: patchNotificationPreferences,
    onSuccess: (data) => {
      queryClient.setQueryData(["notifications", "preferences"], data);
    },
  });

  const items = (prefsQuery.data?.items ?? []).filter((item) => isKnownCategory(item.category));

  async function updatePreference(
    category: string,
    patch: { in_app_enabled?: boolean; push_enabled?: boolean },
  ) {
    setPermissionHint(null);
    setSavingCategory(category);
    try {
      if (patch.push_enabled === true) {
        let state = await getPushPermissionState();
        if (state === "undetermined") {
          state = await requestPushPermission();
        }
        if (state === "denied") {
          setPermissionHint("Push permission was denied. In-app notifications still work.");
          return;
        }
        if (state === "settings_required") {
          setPermissionHint("Enable notifications in system Settings to receive push alerts.");
          return;
        }
        if (state === "unavailable") {
          setPermissionHint("Push notifications are unavailable on this device.");
          return;
        }
        await patchMutation.mutateAsync([{ category, push_enabled: true }]);
        const result = await registerCurrentDevicePushToken();
        if (result === "failed") {
          setPermissionHint("Could not register this device for push. Try again later.");
        }
        return;
      }
      if (patch.push_enabled === false) {
        await patchMutation.mutateAsync([{ category, push_enabled: false }]);
        await unregisterCurrentDevicePushToken();
        return;
      }
      if (patch.in_app_enabled === false && isMandatoryInAppCategory(category)) {
        setPermissionHint("Account in-app notifications stay on for security notices.");
        return;
      }
      await patchMutation.mutateAsync([{ category, ...patch }]);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not update preferences.";
      setPermissionHint(message);
      void queryClient.invalidateQueries({ queryKey: ["notifications", "preferences"] });
    } finally {
      setSavingCategory(null);
    }
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          onPress={() => router.back()}
          style={styles.backButton}
        >
          <Text style={styles.backText}>Back</Text>
        </Pressable>
        <Text style={styles.title} accessibilityRole="header">
          Preferences
        </Text>
        <View style={styles.spacer} />
      </View>

      {prefsQuery.isLoading ? (
        <View style={styles.centered}>
          <ActivityIndicator color={colors.neon} />
        </View>
      ) : null}

      {prefsQuery.isError ? (
        <View style={styles.centered}>
          <Text style={styles.body}>Could not load preferences.</Text>
          <Pressable onPress={() => void prefsQuery.refetch()} style={styles.retry}>
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : null}

      <View style={styles.list}>
        {items.map((item) => {
          const mandatory = isMandatoryInAppCategory(item.category);
          const busy = savingCategory === item.category;
          return (
            <View
              key={item.category}
              style={styles.card}
              testID={`pref-category-${item.category}`}
            >
              <Text style={styles.category}>{categoryLabel(item.category)}</Text>
              <View style={styles.toggleRow}>
                <Text style={styles.toggleLabel}>In-app</Text>
                <Switch
                  accessibilityLabel={`${categoryLabel(item.category)} in-app notifications`}
                  value={item.in_app_enabled}
                  disabled={mandatory || busy}
                  onValueChange={(value) =>
                    void updatePreference(item.category, { in_app_enabled: value })
                  }
                  trackColor={{ false: "#333", true: colors.neon }}
                  thumbColor="#fff"
                />
              </View>
              {mandatory ? (
                <Text style={styles.hint}>Required for account and security notices.</Text>
              ) : null}
              <View style={styles.toggleRow}>
                <Text style={styles.toggleLabel}>Push</Text>
                <Switch
                  accessibilityLabel={`${categoryLabel(item.category)} push notifications`}
                  value={item.push_enabled}
                  disabled={busy}
                  onValueChange={(value) =>
                    void updatePreference(item.category, { push_enabled: value })
                  }
                  trackColor={{ false: "#333", true: colors.neon }}
                  thumbColor="#fff"
                />
              </View>
            </View>
          );
        })}
      </View>

      {permissionHint ? (
        <View style={styles.hintBox}>
          <Text style={styles.hint}>{permissionHint}</Text>
          {permissionHint.includes("Settings") ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Open system settings"
              onPress={() => void Linking.openSettings()}
              style={styles.retry}
            >
              <Text style={styles.retryText}>Open Settings</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  backButton: { minWidth: 64, paddingVertical: 8 },
  backText: { color: colors.neon, fontFamily: fontFamilies.geistMedium, fontSize: 15 },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
  },
  spacer: { width: 64 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12 },
  list: { padding: spacing.md, gap: 12 },
  card: {
    padding: 14,
    borderRadius: 16,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    gap: 10,
  },
  category: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 16,
  },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  toggleLabel: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
  },
  hint: {
    color: colors.textTertiary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
    lineHeight: 16,
  },
  hintBox: { paddingHorizontal: spacing.md, gap: 8 },
  body: { color: colors.textSecondary, fontFamily: fontFamilies.geistRegular },
  retry: {
    alignSelf: "flex-start",
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.borderActive,
  },
  retryText: { color: colors.neon, fontFamily: fontFamilies.geistMedium },
});
