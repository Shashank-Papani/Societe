import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { requestOtp, useOtpLogin } from "@/auth/localAuth";

export function OtpScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ email?: string }>();
  const email = typeof params.email === "string" ? params.email : "";
  const verify = useOtpLogin();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(60);

  useEffect(() => {
    if (seconds <= 0) {
      return;
    }
    const id = setTimeout(() => setSeconds((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [seconds]);

  async function onVerify() {
    setError(null);
    if (code.trim().length < 4) {
      setError("Enter the code from your email.");
      return;
    }
    setBusy(true);
    try {
      const result = await verify(email, code);
      if (result.auth_status === "reactivation_required") {
        setError("This account is deactivated. Confirm reactivation in Profile.");
        router.replace("/(tabs)/profile");
        return;
      }
      if (
        result.user.onboarding_state &&
        result.user.onboarding_state !== "completed"
      ) {
        router.replace("/onboarding");
        return;
      }
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid or expired code.");
    } finally {
      setBusy(false);
    }
  }

  async function onResend() {
    if (seconds > 0) {
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const data = await requestOtp(email);
      setSeconds(data.resend_after_seconds);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to resend.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.title}>Enter code</Text>
      <Text style={styles.help}>Sent to {email}. Check Mailpit in local development.</Text>
      <TextInput
        keyboardType="number-pad"
        maxLength={8}
        placeholder="123456"
        placeholderTextColor="#6b7280"
        style={styles.input}
        value={code}
        onChangeText={setCode}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable style={styles.button} disabled={busy} onPress={() => void onVerify()}>
        {busy ? <ActivityIndicator color="#0b1220" /> : <Text style={styles.buttonText}>Verify</Text>}
      </Pressable>
      <Pressable disabled={busy || seconds > 0} onPress={() => void onResend()}>
        <Text style={styles.resend}>
          {seconds > 0 ? `Resend in ${seconds}s` : "Resend code"}
        </Text>
      </Pressable>
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
    letterSpacing: 4,
  },
  button: {
    backgroundColor: "#f5f7fb",
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
  },
  buttonText: { color: "#0b1220", fontWeight: "600" },
  error: { color: "#fca5a5", marginBottom: 8 },
  resend: { color: "#9aa6bf", marginTop: 16, textAlign: "center" },
});
