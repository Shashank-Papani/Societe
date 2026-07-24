import Constants from "expo-constants";

import { getLiveAccessToken, getUnauthorizedHandler } from "@/auth/AuthProvider";

const extra = Constants.expoConfig?.extra as { apiBaseUrl?: string } | undefined;

export const API_BASE_URL = extra?.apiBaseUrl ?? "http://localhost:8000";

export type ApiEnvelope<T> = {
  data: T;
  meta: { request_id: string; server_time: string };
  error: { code: string; message: string; details?: Record<string, unknown> } | null;
};

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  options: { auth?: boolean } = { auth: true },
): Promise<ApiEnvelope<T>> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (options.auth !== false) {
    const token = getLiveAccessToken();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });
  const body = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok) {
    if (response.status === 401) {
      const handler = getUnauthorizedHandler();
      if (handler) {
        await handler();
      }
    }
    const message = body.error?.message ?? `Request failed (${response.status})`;
    throw new ApiError(response.status, body.error?.code ?? "HTTP_ERROR", message);
  }
  return body;
}
