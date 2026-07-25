import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import * as Crypto from "expo-crypto";

import { useAuth } from "@/auth/AuthProvider";
import { getStoredDeviceId } from "@/auth/deviceStore";
import {
  fetchPresenceMe,
  leavePresence,
  submitPresenceEvidence,
  submitSimulatedPresence,
} from "@/features/presence/api";
import { getLocationProvider } from "@/location/LocationProvider";

let clientSequence = 0;

export function PresenceScreen() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const presenceQuery = useQuery({
    queryKey: ["presence", "me"],
    queryFn: fetchPresenceMe,
    enabled: auth.status === "authenticated",
    refetchInterval: 30_000,
  });

  const refreshMutation = useMutation({
    mutationFn: async () => {
      const deviceId = await getStoredDeviceId();
    
      if (!deviceId) {
        throw new Error("Register a device first (sign in on Profile).");
      }
    
      const provider = getLocationProvider();
      const sample = await provider.getCurrentSample();
    
      if (!sample) {
        throw new Error("Location permission denied or unavailable.");
      }
    
      clientSequence += 1;
    
      const horizontalAccuracy =
        Number.isFinite(sample.horizontal_accuracy_m) &&
        sample.horizontal_accuracy_m > 0
          ? sample.horizontal_accuracy_m
          : 8;
    
      const altitude =
        sample.altitude_m !== null && Number.isFinite(sample.altitude_m)
          ? sample.altitude_m
          : null;
    
      const speed =
        sample.speed_mps !== null &&
        Number.isFinite(sample.speed_mps) &&
        sample.speed_mps >= 0
          ? sample.speed_mps
          : null;
    
      // Development builds use the backend's protected simulator endpoint.
      if (__DEV__) {
        return submitSimulatedPresence({
          latitude: sample.latitude,
          longitude: sample.longitude,
          horizontal_accuracy_m: horizontalAccuracy,
          altitude_m: altitude,
          speed_mps: speed,
          provider: "simulated",
          candidate_venue_id: null,
          client_sequence: clientSequence,
          device_id: deviceId,
        });
      }
    
      // Release builds use the normal strict presence endpoint.
      return submitPresenceEvidence({
        evidence_id: Crypto.randomUUID(),
        observed_at: sample.observed_at,
        location: {
          latitude: sample.latitude,
          longitude: sample.longitude,
          horizontal_accuracy_m: horizontalAccuracy,
          altitude_m: altitude,
          speed_mps: speed,
          provider: sample.provider === "fused" ? "fused" : "gps",
        },
        platform_signals: {
          is_mock: sample.is_mock ?? false,
          is_simulated: false,
          app_state: "foreground",
        },
        client_sequence: clientSequence,
        device_id: deviceId,
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["presence", "me"], data);
    },
  });

  const leaveMutation = useMutation({
    mutationFn: leavePresence,
    onSuccess: (data) => {
      queryClient.setQueryData(["presence", "me"], data);
    },
  });

  const snapshot = presenceQuery.data;

  return (
    <View style={styles.container}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.title}>Presence</Text>
      <Text style={styles.subtitle}>Server-authoritative venue lease (foreground)</Text>

      {auth.status === "initializing" || presenceQuery.isLoading ? (
        <ActivityIndicator color="#9aa6bf" />
      ) : null}

      {auth.status === "unauthenticated" ? (
        <Text style={styles.help}>Sign in on Profile to submit location evidence.</Text>
      ) : null}

      {auth.status === "authenticated" && snapshot ? (
        <View style={styles.block}>
          <Text style={styles.row}>State: {snapshot.state}</Text>
          <Text style={styles.row}>
            Venue: {snapshot.venue ? snapshot.venue.name : "—"}
          </Text>
          <Text style={styles.row}>
            Verification: {snapshot.verification_level ?? "—"}
          </Text>
          <Text style={styles.row}>
            Lease: {snapshot.lease_expires_at ?? "—"}
          </Text>
          <Text style={styles.row}>
            Social eligible: {snapshot.social_features_enabled ? "yes" : "no"}
          </Text>
          {snapshot.reasons.length > 0 ? (
            <Text style={styles.meta}>Reasons: {snapshot.reasons.join(", ")}</Text>
          ) : null}

          <Pressable
            style={styles.button}
            onPress={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
          >
            <Text style={styles.buttonText}>
              {refreshMutation.isPending ? "Checking…" : "Submit foreground evidence"}
            </Text>
          </Pressable>
          <Pressable
            style={styles.buttonSecondary}
            onPress={() => leaveMutation.mutate()}
            disabled={leaveMutation.isPending}
          >
            <Text style={styles.buttonText}>Leave venue</Text>
          </Pressable>
          {refreshMutation.error ? (
            <Text style={styles.error}>{(refreshMutation.error as Error).message}</Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
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
  subtitle: {
    color: "#9aa6bf",
    fontSize: 13,
    marginBottom: 8,
  },
  block: {
    gap: 10,
  },
  row: {
    color: "#c8d0e0",
    fontSize: 15,
  },
  meta: {
    color: "#6f7c99",
    fontSize: 12,
  },
  help: {
    color: "#9aa6bf",
  },
  button: {
    backgroundColor: "#3b82f6",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 8,
  },
  buttonSecondary: {
    backgroundColor: "#334155",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: "center",
  },
  buttonText: {
    color: "#fff",
    fontWeight: "600",
  },
  error: {
    color: "#f87171",
  },
});
