import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as Crypto from "expo-crypto";

import { getStoredDeviceId } from "@/auth/deviceStore";
import {
  submitPresenceEvidence,
  submitSimulatedPresence,
  type PresenceSnapshot,
} from "@/features/presence/api";
import { mapOutsidePresenceReasons, mapPresenceError } from "@/features/presence/presenceErrors";
import { getLocationProvider } from "@/location/LocationProvider";

let clientSequence = 0;

export function useVerifyPresence() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { candidateVenueId: string | null }): Promise<PresenceSnapshot> => {
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
        Number.isFinite(sample.horizontal_accuracy_m) && sample.horizontal_accuracy_m > 0
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

      if (__DEV__) {
        return submitSimulatedPresence({
          latitude: sample.latitude,
          longitude: sample.longitude,
          horizontal_accuracy_m: horizontalAccuracy,
          altitude_m: altitude,
          speed_mps: speed,
          provider: "simulated",
          candidate_venue_id: input.candidateVenueId,
          client_sequence: clientSequence,
          device_id: deviceId,
        });
      }

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
        candidate_venue_id: input.candidateVenueId,
        client_sequence: clientSequence,
        device_id: deviceId,
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["presence", "me"], data);
    },
  });
}

export function interpretVerifyResult(snapshot: PresenceSnapshot, venueId: string) {
  if (
    snapshot.state === "verified" &&
    snapshot.venue?.id === venueId
  ) {
    return { ok: true as const, snapshot };
  }
  return {
    ok: false as const,
    error: mapOutsidePresenceReasons(snapshot.reasons),
    snapshot,
  };
}

export function friendlyVerifyError(error: unknown) {
  return mapPresenceError(error);
}
