import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { isValidEmail, requestOtp, useLocalLogin, DEV_PERSONAS } from "@/auth/localAuth";

export function EmailScreen() {
  const router = useRouter();
  const login = useLocalLogin();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onContinue() {
    setError(null);
    if (!isValidEmail(email)) {
      setError("Enter a valid email address.");
      return;
    }
    setBusy(true);
    try {
      await requestOtp(email);
      router.push({ pathname: "/auth/otp", params: { email: email.trim().toLowerCase() } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to send code.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.title}>Sign in</Text>
      <Text style={styles.help}>We will email you a one-time code. No password.</Text>
      <TextInput
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        placeholder="you@example.com"
        placeholderTextColor="#6b7280"
        style={styles.input}
        value={email}
        onChangeText={setEmail}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable style={styles.button} disabled={busy} onPress={() => void onContinue()}>
        {busy ? <ActivityIndicator color="#0b1220" /> : <Text style={styles.buttonText}>Continue</Text>}
      </Pressable>

      {__DEV__ ? (
        <View style={styles.dev}>
          <Text style={styles.label}>Development personas</Text>
          {DEV_PERSONAS.map((persona) => (
            <Pressable
              key={persona.key}
              style={styles.buttonSecondary}
              disabled={busy}
              onPress={() => {
                setBusy(true);
                void login(persona.key)
                  .then(() => router.replace("/"))
                  .catch((err: Error) => setError(err.message))
                  .finally(() => setBusy(false));
              }}
            >
              <Text style={styles.buttonSecondaryText}>Continue as {persona.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b1220", padding: 24, justifyContent: "center" },
  brand: { color: "#f5f7fb", fontSize: 34, fontWeight: "700", marginBottom: 8 },
  title: { color: "#f5f7fb", fontSize: 22, marginBottom: 8 },
  help: { color: "#9aa6bf", marginBottom: 16 },
  input: {
    borderWidth: 1,
    borderColor: "#243044",
    borderRadius: 10,
    color: "#f5f7fb",
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginBottom: 12,
  },
  button: {
    backgroundColor: "#f5f7fb",
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
  },
  buttonText: { color: "#0b1220", fontWeight: "600" },
  buttonSecondary: {
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 8,
  },
  buttonSecondaryText: { color: "#f5f7fb" },
  error: { color: "#fca5a5", marginBottom: 8 },
  dev: { marginTop: 28 },
  label: { color: "#9aa6bf", marginBottom: 8 },
});
