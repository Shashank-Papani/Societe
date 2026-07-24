import { z } from "zod";
import { Platform } from "react-native";

import { apiFetch } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { getOrCreateInstallationId, saveDeviceId } from "@/auth/deviceStore";

const tokenSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in_minutes: z.number(),
  subject: z.string(),
  handle: z.string(),
});

const meSchema = z.object({
  id: z.string(),
  handle: z.string(),
  display_name: z.string(),
  bio: z.string().nullable().optional(),
  age_verified: z.boolean(),
  age_band: z.string().nullable().optional(),
  account_status: z.string(),
  privacy: z.object({
    ghost_mode: z.boolean(),
    discoverable_in_venue: z.boolean(),
    allow_calling_cards: z.boolean(),
    show_social_links_after_accept: z.boolean(),
    analytics_opt_out: z.boolean(),
    effective: z.object({
      discoverable_in_venue: z.boolean(),
      allow_calling_cards: z.boolean(),
      ghost_mode_overrides: z.boolean(),
    }),
  }),
  created_at: z.string(),
  updated_at: z.string(),
});

const deviceSchema = z.object({
  id: z.string(),
  platform: z.string(),
  installation_id: z.string(),
});

export type MeUser = z.infer<typeof meSchema>;

export async function fetchMe(): Promise<MeUser> {
  const envelope = await apiFetch<MeUser>("/v1/me");
  return meSchema.parse(envelope.data);
}

export async function issueLocalDevToken(): Promise<string> {
  const envelope = await apiFetch<z.infer<typeof tokenSchema>>(
    "/v1/auth/local/token",
    {
      method: "POST",
      body: JSON.stringify({}),
    },
    { auth: false },
  );
  const token = tokenSchema.parse(envelope.data);
  return token.access_token;
}

async function registerCurrentDevice(): Promise<void> {
  const installationId = await getOrCreateInstallationId();
  const platform = Platform.OS === "ios" ? "ios" : "android";
  const envelope = await apiFetch<z.infer<typeof deviceSchema>>("/v1/me/devices", {
    method: "POST",
    headers: { "Idempotency-Key": `device-${installationId}` },
    body: JSON.stringify({
      platform,
      installation_id: installationId,
      app_version: "0.1.0",
      os_version: "dev",
    }),
  });
  const device = deviceSchema.parse(envelope.data);
  await saveDeviceId(device.id);
}

/** Hook-friendly login used by Profile — updates AuthProvider immediately. */
export function useLocalLogin() {
  const auth = useAuth();
  return async () => {
    const token = await issueLocalDevToken();
    await auth.setSession(token);
    try {
      await registerCurrentDevice();
    } catch {
      // Best-effort; Presence will surface a clear error if missing.
    }
    return fetchMe();
  };
}
