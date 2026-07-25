import { Platform } from "react-native";
import { z } from "zod";

import { apiFetch } from "@/api/client";
import { subjectFromAccessToken } from "@/auth/authSubject";
import { useAuth } from "@/auth/AuthProvider";
import {
  getOrCreateInstallationId,
  newUuid,
  persistInstallationId,
  saveDeviceId,
  setActiveAuthSubject,
} from "@/auth/deviceStore";
import { isValidEmail } from "@/auth/emailValidation";

export { isValidEmail };

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

const privacySchema = z.object({
  ghost_mode: z.boolean(),
  discoverable_in_venue: z.boolean(),
  allow_calling_cards: z.boolean(),
  allow_messages_from_connections: z.boolean().optional(),
  show_social_links_after_accept: z.boolean(),
  analytics_opt_out: z.boolean(),
  notify_calling_cards: z.boolean().optional(),
  notify_messages: z.boolean().optional(),
  effective: z.object({
    discoverable_in_venue: z.boolean(),
    allow_calling_cards: z.boolean(),
    allow_messages_from_connections: z.boolean().optional(),
    ghost_mode_overrides: z.boolean(),
  }),
});

const meSchema = z.object({
  id: z.string(),
  handle: z.string(),
  display_name: z.string(),
  bio: z.string().nullable().optional(),
  age_verified: z.boolean(),
  age_band: z.string().nullable().optional(),
  account_status: z.string(),
  onboarding_state: z.string().optional(),
  onboarding_completed: z.boolean().optional(),
  handle_locked: z.boolean().optional(),
  date_of_birth: z.string().nullable().optional(),
  interests: z.array(z.string()).optional(),
  profile_photo_url: z.string().nullable().optional(),
  required_policy_versions: z
    .object({
      terms_of_service: z.string(),
      privacy_policy: z.string(),
    })
    .optional(),
  minimum_age_years: z.number().optional(),
  privacy: privacySchema,
  created_at: z.string(),
  updated_at: z.string(),
});

const deviceSchema = z.object({
  id: z.string(),
  platform: z.string(),
  installation_id: z.string(),
});

const otpVerifySchema = z.object({
  auth_status: z.string(),
  is_new_user: z.boolean(),
  access_token: z.string().nullable().optional(),
  refresh_token: z.string().nullable().optional(),
  expires_in_minutes: z.number().optional(),
  device_id: z.string().optional(),
  session_id: z.string().optional(),
  user: meSchema,
});

export type MeUser = z.infer<typeof meSchema>;

export async function fetchMe(): Promise<MeUser> {
  const envelope = await apiFetch<MeUser>("/v1/me");
  return meSchema.parse(envelope.data);
}

export async function requestOtp(email: string): Promise<{
  message: string;
  expires_in_seconds: number;
  resend_after_seconds: number;
}> {
  const envelope = await apiFetch<{
    message: string;
    expires_in_seconds: number;
    resend_after_seconds: number;
  }>(
    "/v1/auth/otp/request",
    { method: "POST", body: JSON.stringify({ email: email.trim().toLowerCase() }) },
    { auth: false },
  );
  return envelope.data;
}

export async function verifyOtp(input: {
  email: string;
  code: string;
  installationId: string;
}): Promise<z.infer<typeof otpVerifySchema>> {
  const platform = Platform.OS === "ios" ? "ios" : "android";
  const envelope = await apiFetch<z.infer<typeof otpVerifySchema>>(
    "/v1/auth/otp/verify",
    {
      method: "POST",
      body: JSON.stringify({
        email: input.email.trim().toLowerCase(),
        code: input.code.trim(),
        platform,
        installation_id: input.installationId,
        app_version: "0.1.0",
        os_version: "dev",
      }),
    },
    { auth: false },
  );
  return otpVerifySchema.parse(envelope.data);
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

export function useOtpLogin() {
  const auth = useAuth();
  return async (email: string, code: string) => {
    // Installation id is generated in memory — never namespace SecureStore by email.
    const installationId = newUuid();
    const result = await verifyOtp({ email, code, installationId });
    if (result.access_token) {
      const subject = subjectFromAccessToken(result.access_token);
      await setActiveAuthSubject(subject);
      await persistInstallationId(subject, installationId);
      if (result.device_id) {
        await saveDeviceId(result.device_id, subject);
      }
      await auth.setSession(result.access_token, result.refresh_token ?? null);
    }
    return result;
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

export async function patchPrivacy(patch: Record<string, boolean>): Promise<MeUser> {
  const envelope = await apiFetch<MeUser>("/v1/me/privacy", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  return meSchema.parse(envelope.data);
}

export async function signOutRemote(refreshToken: string | null): Promise<void> {
  if (!refreshToken) {
    return;
  }
  await apiFetch(
    "/v1/auth/logout",
    { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) },
    { auth: false },
  ).catch(() => undefined);
}
