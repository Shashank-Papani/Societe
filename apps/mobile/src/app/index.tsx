import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { API_BASE_URL } from "@/api/client";
import { fetchMe, loginWithLocalDevToken, logout } from "@/auth/localAuth";

export default function HomeScreen() {
  const queryClient = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    retry: false,
  });

  const loginMutation = useMutation({
    mutationFn: loginWithLocalDevToken,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });

  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: () => queryClient.setQueryData(["me"], null),
  });

  return (
    <View style={styles.container}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.subtitle}>Phase 0 foundation</Text>
      <Text style={styles.meta}>API: {API_BASE_URL}</Text>

      {meQuery.isLoading ? <ActivityIndicator /> : null}

      {meQuery.data ? (
        <View style={styles.card}>
          <Text style={styles.label}>Signed in</Text>
          <Text>subject: {meQuery.data.subject}</Text>
          <Text>handle: {meQuery.data.handle}</Text>
          <Text>provider: {meQuery.data.auth_provider}</Text>
          <Pressable style={styles.buttonSecondary} onPress={() => logoutMutation.mutate()}>
            <Text style={styles.buttonText}>Sign out</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.label}>Local development auth</Text>
          <Text style={styles.help}>
            Uses POST /v1/auth/local/token. Available only when the API runs with
            APP_ENV=development|test and AUTH_PROVIDER=local.
          </Text>
          <Pressable
            style={styles.button}
            onPress={() => loginMutation.mutate()}
            disabled={loginMutation.isPending}
          >
            <Text style={styles.buttonText}>
              {loginMutation.isPending ? "Signing in…" : "Sign in (local JWT)"}
            </Text>
          </Pressable>
          {loginMutation.error ? (
            <Text style={styles.error}>{(loginMutation.error as Error).message}</Text>
          ) : null}
          {meQuery.error ? (
            <Text style={styles.help}>Not signed in yet.</Text>
          ) : null}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "center",
    padding: 24,
    gap: 12,
    backgroundColor: "#0b1220",
  },
  brand: {
    fontSize: 40,
    fontWeight: "700",
    color: "#f5f7fb",
  },
  subtitle: {
    fontSize: 16,
    color: "#9aa6bf",
  },
  meta: {
    fontSize: 12,
    color: "#6f7c99",
    marginBottom: 8,
  },
  card: {
    gap: 10,
    padding: 16,
    borderRadius: 12,
    backgroundColor: "#151d2e",
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
