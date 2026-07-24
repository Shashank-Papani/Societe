import Constants from "expo-constants";

const extra = Constants.expoConfig?.extra as { apiBaseUrl?: string } | undefined;

export const API_BASE_URL = extra?.apiBaseUrl ?? "http://localhost:8000";

export type ApiEnvelope<T> = {
  data: T;
  meta: { request_id: string; server_time: string };
  error: { code: string; message: string; details?: Record<string, unknown> } | null;
};

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiEnvelope<T>> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });
  const body = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok) {
    const message = body.error?.message ?? `Request failed (${response.status})`;
    throw new Error(message);
  }
  return body;
}
