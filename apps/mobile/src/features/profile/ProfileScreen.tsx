import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { API_BASE_URL } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import {
  DEV_PERSONAS,
  fetchMe,
  useLocalLogin,
  useSwitchDevPersona,
  type DevPersona,
  type MeUser,
} from "@/auth/localAuth";

function personaLabelForHandle(handle: string): string | null {
  const match = DEV_PERSONAS.find((p) => p.handle === handle);
  return match ? match.label : null;
}

export function ProfileScreen() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const login = useLocalLogin();
  const switchPersona = useSwitchDevPersona();

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
    retry: false,
  });

  const loginMutation = useMutation({
    mutationFn: (persona?: DevPersona) => login(persona),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
    },
  });

  const switchMutation = useMutation({
    mutationFn: (persona: DevPersona) => switchPersona(persona),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
    },
  });

  const logoutMutation = useMutation({
    mutationFn: () => auth.clearSession(),
  });

  const privacyHint = privacySummary(meQuery.data);
  const activePersona = meQuery.data ? personaLabelForHandle(meQuery.data.handle) : null;
  const busy =
    loginMutation.isPending || switchMutation.isPending || logoutMutation.isPending;

  return (
    <View style={styles.container}>
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
          <Text style={styles.row}>Status: {meQuery.data.account_status}</Text>
          <Text style={styles.row}>{privacyHint}</Text>
          {meQuery.data.bio ? <Text style={styles.bio}>{meQuery.data.bio}</Text> : null}

          {__DEV__ ? (
            <View style={styles.devBlock}>
              <Text style={styles.label}>Active dev persona</Text>
              <Text style={styles.help}>
                {activePersona ?? "Custom / .env local user"} · @{meQuery.data.handle}
              </Text>
              {DEV_PERSONAS.map((persona) => (
                <Pressable
                  key={persona.key}
                  style={styles.button}
                  disabled={busy || meQuery.data?.handle === persona.handle}
                  onPress={() => switchMutation.mutate(persona.key)}
                >
                  <Text style={styles.buttonText}>
                    {switchMutation.isPending && switchMutation.variables === persona.key
                      ? "Switching…"
                      : `Switch to ${persona.label}`}
                  </Text>
                </Pressable>
              ))}
              {switchMutation.error ? (
                <Text style={styles.error}>{(switchMutation.error as Error).message}</Text>
              ) : null}
            </View>
          ) : null}

          <Pressable style={styles.buttonSecondary} onPress={() => logoutMutation.mutate()}>
            <Text style={styles.buttonText}>Sign out</Text>
          </Pressable>
        </View>
      ) : auth.status !== "initializing" ? (
        <View style={styles.block}>
          <Text style={styles.label}>Local development auth</Text>
          <Text style={styles.help}>
            Signs in via POST /v1/auth/local/token when AUTH_PROVIDER=local.
          </Text>

          {__DEV__ ? (
            <>
              {DEV_PERSONAS.map((persona) => (
                <Pressable
                  key={persona.key}
                  style={styles.button}
                  disabled={busy}
                  onPress={() => loginMutation.mutate(persona.key)}
                >
                  <Text style={styles.buttonText}>
                    {loginMutation.isPending && loginMutation.variables === persona.key
                      ? "Signing in…"
                      : `Continue as ${persona.label}`}
                  </Text>
                </Pressable>
              ))}
            </>
          ) : (
            <Pressable
              style={styles.button}
              onPress={() => loginMutation.mutate(undefined)}
              disabled={busy}
            >
              <Text style={styles.buttonText}>
                {loginMutation.isPending ? "Signing in…" : "Sign in (local JWT)"}
              </Text>
            </Pressable>
          )}

          {loginMutation.error ? (
            <Text style={styles.error}>{(loginMutation.error as Error).message}</Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function privacySummary(user: MeUser | null | undefined): string {
  if (!user) {
    return "";
  }
  const ghost = user.privacy.effective.ghost_mode_overrides;
  if (ghost) {
    return "Ghost Mode on · social discovery suppressed (client hint)";
  }
  return user.privacy.discoverable_in_venue
    ? "Discoverable in venue (enforcement in later phases)"
    : "Not discoverable in venue";
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#0b1220",
    paddingTop: 56,
    paddingHorizontal: 20,
    gap: 10,
  },
  brand: {
    fontSize: 28,
    fontWeight: "700",
    color: "#f5f7fb",
  },
  title: {
    fontSize: 22,
    fontWeight: "600",
    color: "#f5f7fb",
  },
  meta: {
    fontSize: 12,
    color: "#6f7c99",
    marginBottom: 8,
  },
  block: {
    gap: 10,
  },
  devBlock: {
    gap: 8,
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "#1e293b",
  },
  handle: {
    color: "#f5f7fb",
    fontSize: 20,
    fontWeight: "600",
  },
  display: {
    color: "#9aa6bf",
    fontSize: 16,
  },
  row: {
    color: "#9aa6bf",
    fontSize: 14,
  },
  bio: {
    color: "#c8d0e0",
    lineHeight: 20,
  },
  label: {
    fontSize: 18,
    fontWeight: "600",
    color: "#f5f7fb",
  },
  help: {
    color: "#9aa6bf",
    lineHeight: 20,
  },
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
  buttonText: {
    color: "#fff",
    fontWeight: "600",
  },
  error: {
    color: "#f87171",
  },
});
