import { z } from "zod";

import { apiFetch } from "@/api/client";
import { clearAccessToken, getAccessToken, saveAccessToken } from "@/auth/tokenStore";

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

export type MeUser = z.infer<typeof meSchema>;

export async function loginWithLocalDevToken(): Promise<MeUser> {
  const envelope = await apiFetch<z.infer<typeof tokenSchema>>("/v1/auth/local/token", {
    method: "POST",
    body: JSON.stringify({}),
  });
  const token = tokenSchema.parse(envelope.data);
  await saveAccessToken(token.access_token);
  return fetchMe();
}

export async function fetchMe(): Promise<MeUser> {
  const accessToken = await getAccessToken();
  if (!accessToken) {
    throw new Error("Not signed in");
  }
  const envelope = await apiFetch<MeUser>("/v1/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return meSchema.parse(envelope.data);
}

export async function logout(): Promise<void> {
  await clearAccessToken();
}
