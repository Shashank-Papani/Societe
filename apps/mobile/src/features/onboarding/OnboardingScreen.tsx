import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";

import { apiFetch } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { fetchMe, type MeUser } from "@/auth/localAuth";

type PrivacyChoices = {
  discoverable_in_venue: boolean;
  allow_calling_cards: boolean;
  allow_messages_from_connections: boolean;
  show_social_links_after_accept: boolean;
};

export function OnboardingScreen() {
  const auth = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
  });
  const me = meQuery.data;
  const [handle, setHandle] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [dob, setDob] = useState("");
  const [privacy, setPrivacy] = useState<PrivacyChoices>({
    discoverable_in_venue: false,
    allow_calling_cards: false,
    allow_messages_from_connections: false,
    show_social_links_after_accept: false,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refreshMe(): Promise<MeUser> {
    const next = await fetchMe();
    queryClient.setQueryData(["me"], next);
    return next;
  }

  async function submitProfile() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/v1/me/onboarding/profile", {
        method: "POST",
        body: JSON.stringify({ handle, display_name: displayName }),
      });
      await refreshMe();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Profile step failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitAge() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/v1/me/onboarding/age", {
        method: "POST",
        body: JSON.stringify({ date_of_birth: dob }),
      });
      const next = await refreshMe();
      if (next.onboarding_state === "age_ineligible") {
        setError("You do not meet the minimum age for Société.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Age step failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitPolicies() {
    setBusy(true);
    setError(null);
    try {
      const versions = me?.required_policy_versions;
      if (!versions) {
        throw new Error("Policy versions unavailable.");
      }
      await apiFetch("/v1/me/onboarding/policies", {
        method: "POST",
        body: JSON.stringify({
          tos_version: versions.terms_of_service,
          privacy_policy_version: versions.privacy_policy,
        }),
      });
      await refreshMe();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Policy step failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitPrivacy() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/v1/me/onboarding/privacy", {
        method: "POST",
        body: JSON.stringify(privacy),
      });
      await refreshMe();
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Privacy step failed.");
    } finally {
      setBusy(false);
    }
  }

  if (auth.status === "initializing" || meQuery.isLoading || !me) {
    return (
      <View style={styles.container}>
        <ActivityIndicator color="#9aa6bf" />
      </View>
    );
  }

  const state = me.onboarding_state ?? "completed";

  return (
    <View style={styles.container}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.title}>Finish setup</Text>
      <Text style={styles.meta}>Step: {state.replaceAll("_", " ")}</Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}

      {state === "profile_required" || state === "authentication_verified" ? (
        <View style={styles.block}>
          <TextInput
            placeholder="username"
            placeholderTextColor="#6b7280"
            autoCapitalize="none"
            style={styles.input}
            value={handle}
            onChangeText={setHandle}
          />
          <TextInput
            placeholder="Display name"
            placeholderTextColor="#6b7280"
            style={styles.input}
            value={displayName}
            onChangeText={setDisplayName}
          />
          <Pressable style={styles.button} disabled={busy} onPress={() => void submitProfile()}>
            <Text style={styles.buttonText}>Continue</Text>
          </Pressable>
        </View>
      ) : null}

      {state === "age_required" ? (
        <View style={styles.block}>
          <Text style={styles.help}>Date of birth (YYYY-MM-DD). Minimum age {me.minimum_age_years ?? 18}.</Text>
          <TextInput
            placeholder="1995-01-15"
            placeholderTextColor="#6b7280"
            style={styles.input}
            value={dob}
            onChangeText={setDob}
          />
          <Pressable style={styles.button} disabled={busy} onPress={() => void submitAge()}>
            <Text style={styles.buttonText}>Continue</Text>
          </Pressable>
        </View>
      ) : null}

      {state === "age_ineligible" ? (
        <View style={styles.block}>
          <Text style={styles.help}>
            This account cannot use social features. You may sign out or request account deletion
            from Profile.
          </Text>
          <Pressable style={styles.button} onPress={() => void auth.clearSession()}>
            <Text style={styles.buttonText}>Sign out</Text>
          </Pressable>
        </View>
      ) : null}

      {state === "policy_acceptance_required" ? (
        <View style={styles.block}>
          <Text style={styles.help}>
            Accept Terms {me.required_policy_versions?.terms_of_service} and Privacy Policy{" "}
            {me.required_policy_versions?.privacy_policy}.
          </Text>
          <Pressable style={styles.button} disabled={busy} onPress={() => void submitPolicies()}>
            <Text style={styles.buttonText}>I accept</Text>
          </Pressable>
        </View>
      ) : null}

      {state === "privacy_required" ? (
        <View style={styles.block}>
          <Text style={styles.help}>Choose each setting explicitly. Defaults stay off until you opt in.</Text>
          {(
            [
              ["discoverable_in_venue", "Discoverable at venues"],
              ["allow_calling_cards", "Allow Calling Cards"],
              ["allow_messages_from_connections", "Allow messages from connections"],
              ["show_social_links_after_accept", "Show social links after accept"],
            ] as const
          ).map(([key, label]) => (
            <View key={key} style={styles.row}>
              <Text style={styles.rowLabel}>{label}</Text>
              <Switch
                value={privacy[key]}
                onValueChange={(value) => setPrivacy((prev) => ({ ...prev, [key]: value }))}
              />
            </View>
          ))}
          <Pressable style={styles.button} disabled={busy} onPress={() => void submitPrivacy()}>
            <Text style={styles.buttonText}>Enter Société</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b1220", padding: 24, justifyContent: "center" },
  brand: { color: "#f5f7fb", fontSize: 34, fontWeight: "700", marginBottom: 8 },
  title: { color: "#f5f7fb", fontSize: 22, marginBottom: 8 },
  meta: { color: "#9aa6bf", marginBottom: 12 },
  help: { color: "#9aa6bf", marginBottom: 12 },
  block: { gap: 8 },
  input: {
    borderWidth: 1,
    borderColor: "#243044",
    borderRadius: 10,
    color: "#f5f7fb",
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  button: {
    backgroundColor: "#f5f7fb",
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 8,
  },
  buttonText: { color: "#0b1220", fontWeight: "600" },
  error: { color: "#fca5a5", marginBottom: 8 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginVertical: 6,
  },
  rowLabel: { color: "#f5f7fb", flex: 1, paddingRight: 12 },
});
