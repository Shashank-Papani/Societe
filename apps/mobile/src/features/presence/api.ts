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
  grace_expires_at: z.string().nullable().optional(),
  entry_radius_meters: z.number().nullable().optional(),
  retention_radius_meters: z.number().nullable().optional(),
  distance_meters: z.number().nullable().optional(),
  next_recommended_check_at: z.string().nullable().optional(),
  outside_confirmation_pending: z.boolean().optional().default(false),
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

const eligibilitySchema = z.object({
  eligible: z.boolean(),
  reason: z.string(),
  distance_meters: z.number().nullable().optional(),
  allowed_radius_meters: z.number().nullable().optional(),
  location_accuracy_meters: z.number(),
  venue_id: z.string(),
  observed_at: z.string(),
});

export type PresenceEligibility = z.infer<typeof eligibilitySchema>;

export async function fetchPresenceEligibility(body: {
  latitude: number;
  longitude: number;
  horizontal_accuracy_m: number;
  observed_at: string;
  candidate_venue_id: string;
}): Promise<PresenceEligibility> {
  const envelope = await apiFetch<PresenceEligibility>("/v1/presence/eligibility", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return eligibilitySchema.parse(envelope.data);
}

export type PresenceEvidenceBody = {
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
};

export async function submitPresenceEvidence(
  body: PresenceEvidenceBody,
): Promise<PresenceSnapshot> {
  const idempotencyKey = body.evidence_id;
  const envelope = await apiFetch<PresenceSnapshot>("/v1/presence/evidence", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(body),
  });
  return presenceSchema.parse(envelope.data);
}

export type PresenceHeartbeatBody = {
  evidence_id: string;
  observed_at: string;
  location: PresenceEvidenceBody["location"];
  platform_signals: PresenceEvidenceBody["platform_signals"];
  venue_id?: string | null;
  check_in_id?: string | null;
  client_sequence: number;
  device_id: string;
};

export async function submitPresenceHeartbeat(
  body: PresenceHeartbeatBody,
): Promise<PresenceSnapshot> {
  const idempotencyKey = body.evidence_id;
  const envelope = await apiFetch<PresenceSnapshot>("/v1/presence/heartbeat", {
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
