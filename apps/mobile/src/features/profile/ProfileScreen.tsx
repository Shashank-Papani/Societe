import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, type Href } from "expo-router";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_BASE_URL, apiFetch } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { getRefreshToken } from "@/auth/tokenStore";
import {
  DEV_PERSONAS,
  fetchMe,
  patchPrivacy,
  signOutRemote,
  useSwitchDevPersona,
  type DevPersona,
  type MeUser,
} from "@/auth/localAuth";
import { ProfilePhotoSection } from "@/features/profile/ProfilePhotoSection";
import { tabScreenBottomPadding } from "@/navigation/tabBar";
import { colors, fontFamilies, radii, spacing } from "@/theme";

function personaLabelForHandle(handle: string): string | null {
  const match = DEV_PERSONAS.find((p) => p.handle === handle);
  return match ? match.label : null;
}

export function ProfileScreen() {
  const auth = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const switchPersona = useSwitchDevPersona();
  const bottomPad = tabScreenBottomPadding(insets.bottom);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
    retry: false,
  });

  const devicesQuery = useQuery({
    queryKey: ["me", "devices"],
    queryFn: async () => {
      const envelope = await apiFetch<{
        devices: { id: string; platform: string; is_current?: boolean }[];
      }>("/v1/me/devices");
      return envelope.data.devices;
    },
    enabled: auth.status === "authenticated",
  });

  const switchMutation = useMutation({
    mutationFn: (persona: DevPersona) => switchPersona(persona),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
    },
  });

  const privacyMutation = useMutation({
    mutationFn: (patch: Record<string, boolean>) => patchPrivacy(patch),
    onSuccess: (user) => queryClient.setQueryData(["me"], user),
  });

  const logoutMutation = useMutation({
    mutationFn: async () => {
      const refresh = await getRefreshToken();
      await signOutRemote(refresh);
      await auth.clearSession();
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: async () => {
      await apiFetch("/v1/me/account-deactivation", {
        method: "POST",
        body: JSON.stringify({ confirmation: "DEACTIVATE" }),
      });
      await auth.clearSession();
    },
  });

  const privacyHint = privacySummary(meQuery.data);
  const activePersona = meQuery.data ? personaLabelForHandle(meQuery.data.handle) : null;
  const busy =
    switchMutation.isPending ||
    logoutMutation.isPending ||
    privacyMutation.isPending ||
    deactivateMutation.isPending;

  if (auth.status === "unauthenticated") {
    return (
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          style={styles.flex}
          contentContainerStyle={[styles.content, { paddingBottom: bottomPad }]}
          keyboardShouldPersistTaps="handled"
          automaticallyAdjustKeyboardInsets
          showsVerticalScrollIndicator
        >
          <Text style={styles.title}>Profile</Text>
          <Text style={styles.help}>Sign in to manage your profile.</Text>
          <Pressable style={styles.button} onPress={() => router.replace("/auth/email")}>
            <Text style={styles.buttonText}>Sign in</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        style={styles.flex}
        contentContainerStyle={[styles.content, { paddingBottom: bottomPad }]}
        keyboardShouldPersistTaps="handled"
        automaticallyAdjustKeyboardInsets
        showsVerticalScrollIndicator
      >
        <Text style={styles.title} accessibilityRole="header">
          Profile
        </Text>

        {auth.status === "initializing" || meQuery.isLoading ? (
          <ActivityIndicator color={colors.lime} />
        ) : null}

        {auth.status === "authenticated" && meQuery.data ? (
          <View style={styles.block}>
            <ProfilePhotoSection approvedUrl={meQuery.data.profile_photo_url} />
            <Text style={styles.display}>{meQuery.data.display_name}</Text>
            <Text style={styles.handle}>@{meQuery.data.handle}</Text>
            <Text style={styles.row}>{privacyHint}</Text>
            {__DEV__ ? <Text style={styles.meta}>API: {API_BASE_URL}</Text> : null}

            <Text style={styles.label}>Privacy</Text>
            {(
              [
                ["ghost_mode", "Ghost Mode"],
                ["discoverable_in_venue", "Discoverable at venue"],
                ["allow_calling_cards", "Allow Calling Cards"],
                ["allow_messages_from_connections", "Allow messages"],
              ] as const
            ).map(([key, label]) => (
              <View key={key} style={styles.rowSwitch}>
                <Text style={styles.row}>{label}</Text>
                <Switch
                  value={Boolean(meQuery.data?.privacy[key as keyof MeUser["privacy"]])}
                  disabled={busy}
                  onValueChange={(value) => privacyMutation.mutate({ [key]: value })}
                />
              </View>
            ))}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Blocked Users"
              testID="profile-blocked-users"
              onPress={() => router.push("/blocked-users")}
              style={styles.buttonSecondary}
            >
              <Text style={styles.buttonSecondaryText}>Blocked Users</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Notification preferences"
              testID="profile-notification-preferences"
              onPress={() => router.push("/notifications/preferences" as Href)}
              style={styles.buttonSecondary}
            >
              <Text style={styles.buttonSecondaryText}>Notification preferences</Text>
            </Pressable>

            <Text style={styles.label}>Devices</Text>
            {(devicesQuery.data ?? []).map((device) => (
              <Text key={device.id} style={styles.row}>
                {device.platform}
                {device.is_current ? " · this device" : ""} · {device.id.slice(0, 8)}
              </Text>
            ))}

            {__DEV__ ? (
              <View style={styles.devBlock}>
                <Text style={styles.label}>Active dev persona</Text>
                <Text style={styles.help}>
                  {activePersona ?? "Email / custom"} · @{meQuery.data.handle}
                </Text>
                {DEV_PERSONAS.map((persona) => (
                  <Pressable
                    key={persona.key}
                    style={styles.button}
                    disabled={busy || meQuery.data?.handle === persona.handle}
                    onPress={() => switchMutation.mutate(persona.key)}
                  >
                    <Text style={styles.buttonText}>Switch to {persona.label}</Text>
                  </Pressable>
                ))}
              </View>
            ) : null}

            <Pressable style={styles.buttonSecondary} onPress={() => logoutMutation.mutate()}>
              <Text style={styles.buttonSecondaryText}>Sign out</Text>
            </Pressable>
            <Pressable
              style={styles.buttonDanger}
              onPress={() => deactivateMutation.mutate()}
              disabled={busy}
            >
              <Text style={styles.buttonDangerText}>Deactivate account</Text>
            </Pressable>
          </View>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function privacySummary(user: MeUser | null | undefined): string {
  if (!user) {
    return "";
  }
  const ghost = user.privacy.effective.ghost_mode_overrides;
  if (ghost) {
    return "Ghost Mode on · discovery and cards suppressed";
  }
  return user.privacy.discoverable_in_venue
    ? "Discoverable in venue"
    : "Not discoverable in venue";
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
    backgroundColor: colors.backgroundPrimary,
  },
  content: {
    paddingTop: spacing.xxl,
    paddingHorizontal: spacing.lg,
    gap: spacing.sm,
    flexGrow: 1,
  },
  title: {
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 36,
    color: colors.textPrimary,
  },
  meta: {
    fontSize: 12,
    fontFamily: fontFamilies.geistRegular,
    color: colors.textTertiary,
    marginBottom: 8,
  },
  block: { gap: spacing.sm },
  devBlock: {
    gap: 8,
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.borderSubtle,
  },
  handle: {
    color: colors.textSecondary,
    fontSize: 15,
    fontFamily: fontFamilies.geistMedium,
  },
  display: {
    color: colors.textPrimary,
    fontSize: 28,
    fontFamily: fontFamilies.instrumentSerif,
  },
  row: {
    color: colors.textSecondary,
    fontSize: 14,
    fontFamily: fontFamilies.geistRegular,
  },
  rowSwitch: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    minHeight: 44,
  },
  label: {
    fontSize: 13,
    fontFamily: fontFamilies.geistBold,
    color: colors.gold,
    letterSpacing: 1.1,
    marginTop: spacing.md,
  },
  help: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    lineHeight: 20,
  },
  button: {
    backgroundColor: colors.neon,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: radii.pill,
    alignItems: "center",
    minHeight: 48,
    justifyContent: "center",
  },
  buttonSecondary: {
    backgroundColor: colors.surfaceElevated,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderMedium,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: radii.pill,
    alignItems: "center",
    marginTop: 8,
    minHeight: 48,
    justifyContent: "center",
  },
  buttonDanger: {
    backgroundColor: "rgba(255, 107, 107, 0.14)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(255, 107, 107, 0.35)",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: radii.pill,
    alignItems: "center",
    minHeight: 48,
    justifyContent: "center",
  },
  buttonText: {
    color: colors.neonText,
    fontFamily: fontFamilies.geistBold,
    fontSize: 14,
  },
  buttonSecondaryText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistBold,
    fontSize: 14,
  },
  buttonDangerText: {
    color: colors.danger,
    fontFamily: fontFamilies.geistBold,
    fontSize: 14,
  },
});
