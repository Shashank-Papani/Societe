import { z } from "zod";

import { apiFetch } from "@/api/client";

const presenceSchema = z.object({
  state: z.string(),
  venue: z
    .object({
      id: z.string(),
      name: z.string(),
    })
    .nullable(),
  verification_level: z.string().nullable(),
  lease_expires_at: z.string().nullable(),
  social_features_enabled: z.boolean(),
  challenge: z.null(),
  decision: z.string(),
  reasons: z.array(z.string()),
});

export type PresenceSnapshot = z.infer<typeof presenceSchema>;

export async function fetchPresenceMe(): Promise<PresenceSnapshot> {
  const envelope = await apiFetch<PresenceSnapshot>("/v1/presence/me");
  return presenceSchema.parse(envelope.data);
}

export async function submitPresenceEvidence(body: {
  evidence_id: string;
  observed_at: string;
  location: {
    latitude: number;
    longitude: number;
    horizontal_accuracy_m: number;
    altitude_m: number | null;
    speed_mps: number | null;
    provider: "fused" | "gps" | "network" | "simulated";
  };
  platform_signals: {
    is_mock: boolean;
    is_simulated: boolean;
    app_state: "foreground" | "background";
  };
  candidate_venue_id?: string | null;
  client_sequence: number;
  device_id: string;
}): Promise<PresenceSnapshot> {
  const idempotencyKey = body.evidence_id;
  const envelope = await apiFetch<PresenceSnapshot>("/v1/presence/evidence", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(body),
  });
  return presenceSchema.parse(envelope.data);
}

export async function leavePresence(): Promise<PresenceSnapshot> {
  const idempotencyKey = `leave-${Date.now()}`;
  const envelope = await apiFetch<PresenceSnapshot>("/v1/presence/leave", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ confirmation: "LEAVE" }),
  });
  return presenceSchema.parse(envelope.data);
}

export async function submitSimulatedPresence(body: {
  latitude: number;
  longitude: number;
  horizontal_accuracy_m: number;
  altitude_m: number | null;
  speed_mps: number | null;
  provider: "fused" | "gps" | "network" | "simulated";
  candidate_venue_id?: string | null;
  client_sequence: number;
  device_id: string;
}): Promise<PresenceSnapshot> {
  const envelope = await apiFetch<PresenceSnapshot>(
    "/v1/dev/location/simulate",
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );

  return presenceSchema.parse(envelope.data);
}