import Constants from "expo-constants";

import {
  getLiveAccessToken,
  getRefreshHandler,
  getUnauthorizedHandler,
} from "@/auth/AuthProvider";

const extra = Constants.expoConfig?.extra as
  | { apiBaseUrl?: string; realtimeUrl?: string }
  | undefined;

export const API_BASE_URL = extra?.apiBaseUrl ?? "http://localhost:8000";
export const REALTIME_URL =
  extra?.realtimeUrl ?? "ws://localhost:8000/v1/realtime/ws";

export type ApiEnvelope<T> = {
  data: T;
  meta: { request_id: string; server_time: string };
  error: { code: string; message: string; details?: Record<string, unknown> } | null;
};

export class ApiError extends Error {
  status: number;
  code: string;
  retryAfterSeconds: number | null;

  constructor(
    status: number,
    code: string,
    message: string,
    retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function parseRetryAfter(header: string | null): number | null {
  if (!header) {
    return null;
  }
  const asInt = Number.parseInt(header, 10);
  if (Number.isFinite(asInt) && asInt >= 0) {
    return asInt;
  }
  const asDate = Date.parse(header);
  if (!Number.isNaN(asDate)) {
    return Math.max(0, Math.ceil((asDate - Date.now()) / 1000));
  }
  return null;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  options: { auth?: boolean; _retried?: boolean } = { auth: true },
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
    if (response.status === 401 && options.auth !== false && !options._retried) {
      const refresh = getRefreshHandler();
      if (refresh) {
        const next = await refresh();
        if (next) {
          const retryHeaders = new Headers(init.headers);
          if (!retryHeaders.has("Content-Type") && init.body) {
            retryHeaders.set("Content-Type", "application/json");
          }
          retryHeaders.set("Authorization", `Bearer ${next}`);
          return apiFetch<T>(path, { ...init, headers: retryHeaders }, {
            ...options,
            _retried: true,
          });
        }
      }
      const handler = getUnauthorizedHandler();
      if (handler) {
        await handler();
      }
    } else if (response.status === 401) {
      const handler = getUnauthorizedHandler();
      if (handler) {
        await handler();
      }
    }
    const message = body.error?.message ?? `Request failed (${response.status})`;
    throw new ApiError(
      response.status,
      body.error?.code ?? "HTTP_ERROR",
      message,
      parseRetryAfter(response.headers.get("Retry-After")),
    );
  }
  return body;
}
