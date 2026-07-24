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
  subject: z.string(),
  handle: z.string(),
  auth_provider: z.string(),
});

export type LocalUser = z.infer<typeof meSchema>;

export async function loginWithLocalDevToken(): Promise<LocalUser> {
  const envelope = await apiFetch<z.infer<typeof tokenSchema>>("/v1/auth/local/token", {
    method: "POST",
    body: JSON.stringify({}),
  });
  const token = tokenSchema.parse(envelope.data);
  await saveAccessToken(token.access_token);
  return fetchMe();
}

export async function fetchMe(): Promise<LocalUser> {
  const accessToken = await getAccessToken();
  if (!accessToken) {
    throw new Error("Not signed in");
  }
  const envelope = await apiFetch<z.infer<typeof meSchema>>("/v1/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return meSchema.parse(envelope.data);
}

export async function logout(): Promise<void> {
  await clearAccessToken();
}
