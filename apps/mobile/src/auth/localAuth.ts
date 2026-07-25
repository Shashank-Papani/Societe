import { Platform } from "react-native";
import { z } from "zod";

import { apiFetch } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import {
  getOrCreateInstallationId,
  saveDeviceId,
  setActiveAuthSubject,
} from "@/auth/deviceStore";

export type DevPersona = "alpha" | "beta";

export const DEV_PERSONAS: {
  key: DevPersona;
  label: string;
  subject: string;
  handle: string;
}[] = [
  {
    key: "alpha",
    label: "Dev Alpha",
    subject: "dev-user-alpha",
    handle: "devalpha",
  },
  {
    key: "beta",
    label: "Dev Beta",
    subject: "dev-user-beta",
    handle: "devbeta",
  },
];

const tokenSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in_minutes: z.number(),
  subject: z.string(),
  handle: z.string(),
  persona: z.string().nullable().optional(),
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

export async function issueLocalDevToken(persona?: DevPersona): Promise<{
  accessToken: string;
  subject: string;
  handle: string;
  persona: string | null;
}> {
  const envelope = await apiFetch<z.infer<typeof tokenSchema>>(
    "/v1/auth/local/token",
    {
      method: "POST",
      body: JSON.stringify(persona ? { persona } : {}),
    },
    { auth: false },
  );
  const token = tokenSchema.parse(envelope.data);
  return {
    accessToken: token.access_token,
    subject: token.subject,
    handle: token.handle,
    persona: token.persona ?? null,
  };
}

async function registerCurrentDevice(subject: string): Promise<void> {
  const installationId = await getOrCreateInstallationId(subject);
  const platform = Platform.OS === "ios" ? "ios" : "android";
  const envelope = await apiFetch<z.infer<typeof deviceSchema>>("/v1/me/devices", {
    method: "POST",
    headers: { "Idempotency-Key": `device-${subject}-${installationId}` },
    body: JSON.stringify({
      platform,
      installation_id: installationId,
      app_version: "0.1.0",
      os_version: "dev",
    }),
  });
  const device = deviceSchema.parse(envelope.data);
  await saveDeviceId(device.id, subject);
}

/** Hook-friendly login used by Profile — updates AuthProvider immediately. */
export function useLocalLogin() {
  const auth = useAuth();
  return async (persona?: DevPersona) => {
    const issued = await issueLocalDevToken(persona);
    await setActiveAuthSubject(issued.subject);
    await auth.setSession(issued.accessToken);
    try {
      await registerCurrentDevice(issued.subject);
    } catch {
      // Best-effort; Presence will surface a clear error if missing.
    }
    return fetchMe();
  };
}

/** Switch personas: clear session, then sign in as the target persona. */
export function useSwitchDevPersona() {
  const auth = useAuth();
  const login = useLocalLogin();
  return async (persona: DevPersona) => {
    await auth.clearSession();
    return login(persona);
  };
}
