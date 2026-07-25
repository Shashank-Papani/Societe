import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
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
  const bottomPad = Math.max(insets.bottom, 16) + 24;

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
          <Text style={styles.brand}>Société</Text>
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
        <Text style={styles.brand}>Société</Text>
        <Text style={styles.title}>Profile</Text>
        <Text style={styles.meta}>API: {API_BASE_URL}</Text>

        {auth.status === "initializing" || meQuery.isLoading ? (
          <ActivityIndicator color="#9aa6bf" />
        ) : null}

        {auth.status === "authenticated" && meQuery.data ? (
          <View style={styles.block}>
            <Text style={styles.handle}>@{meQuery.data.handle}</Text>
            <Text style={styles.display}>{meQuery.data.display_name}</Text>

            <ProfilePhotoSection approvedUrl={meQuery.data.profile_photo_url} />
            <Text style={styles.row}>Status: {meQuery.data.account_status}</Text>
            <Text style={styles.row}>Onboarding: {meQuery.data.onboarding_state ?? "unknown"}</Text>
            <Text style={styles.row}>{privacyHint}</Text>

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
              <Text style={styles.buttonText}>Sign out</Text>
            </Pressable>
            <Pressable
              style={styles.buttonDanger}
              onPress={() => deactivateMutation.mutate()}
              disabled={busy}
            >
              <Text style={styles.buttonText}>Deactivate account</Text>
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
    backgroundColor: "#0b1220",
  },
  content: {
    paddingTop: 56,
    paddingHorizontal: 20,
    gap: 10,
    flexGrow: 1,
  },
  brand: { fontSize: 28, fontWeight: "700", color: "#f5f7fb" },
  title: { fontSize: 22, fontWeight: "600", color: "#f5f7fb" },
  meta: { fontSize: 12, color: "#6f7c99", marginBottom: 8 },
  block: { gap: 10 },
  devBlock: {
    gap: 8,
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "#1e293b",
  },
  handle: { color: "#f5f7fb", fontSize: 20, fontWeight: "600" },
  display: { color: "#9aa6bf", fontSize: 16 },
  row: { color: "#9aa6bf", fontSize: 14 },
  rowSwitch: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  label: { fontSize: 18, fontWeight: "600", color: "#f5f7fb", marginTop: 8 },
  help: { color: "#9aa6bf", lineHeight: 20 },
  button: {
    backgroundColor: "#3b82f6",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: "center",
  },
  buttonSecondary: {
    backgroundColor: "#334155",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 8,
  },
  buttonDanger: {
    backgroundColor: "#7f1d1d",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: "center",
  },
  buttonText: { color: "#fff", fontWeight: "600" },
});
