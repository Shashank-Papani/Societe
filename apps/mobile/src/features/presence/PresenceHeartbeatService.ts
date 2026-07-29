/**
 * Shared heartbeat submission used by foreground and background retention.
 */

import * as Crypto from "expo-crypto";

import { getStoredDeviceId } from "@/auth/deviceStore";
import {
  submitPresenceHeartbeat,
  type PresenceSnapshot,
} from "@/features/presence/api";
import type { ForegroundLocationSample } from "@/location/LocationProvider";

let clientSequence = 0;

export type HeartbeatSubmitInput = {
  sample: ForegroundLocationSample;
  venueId: string | null;
  appState: "foreground" | "background";
};

export async function submitRetentionHeartbeat(
  input: HeartbeatSubmitInput,
): Promise<PresenceSnapshot | null> {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) {
    return null;
  }

  clientSequence += 1;
  const horizontalAccuracy =
    Number.isFinite(input.sample.horizontal_accuracy_m) &&
    input.sample.horizontal_accuracy_m > 0
      ? input.sample.horizontal_accuracy_m
      : 8;

  const altitude =
    input.sample.altitude_m !== null && Number.isFinite(input.sample.altitude_m)
      ? input.sample.altitude_m
      : null;

  const speed =
    input.sample.speed_mps !== null &&
    Number.isFinite(input.sample.speed_mps) &&
    input.sample.speed_mps >= 0
      ? input.sample.speed_mps
      : null;

  const isSimulated = __DEV__ && (input.sample.is_mock || input.sample.provider === "simulated");

  return submitPresenceHeartbeat({
    evidence_id: Crypto.randomUUID(),
    observed_at: input.sample.observed_at,
    location: {
      latitude: input.sample.latitude,
      longitude: input.sample.longitude,
      horizontal_accuracy_m: horizontalAccuracy,
      altitude_m: altitude,
      speed_mps: speed,
      provider: isSimulated
        ? "simulated"
        : input.sample.provider === "fused"
          ? "fused"
          : "gps",
    },
    platform_signals: {
      is_mock: Boolean(input.sample.is_mock),
      is_simulated: Boolean(isSimulated),
      app_state: input.appState,
    },
    venue_id: input.venueId,
    client_sequence: clientSequence,
    device_id: deviceId,
  });
}
