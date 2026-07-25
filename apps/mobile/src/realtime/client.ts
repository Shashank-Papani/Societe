import Constants from "expo-constants";

import { API_BASE_URL, REALTIME_URL } from "@/api/client";
import { getLiveAccessToken } from "@/auth/AuthProvider";

export type RealtimeEnvelope = {
  event_id?: string;
  event_type?: string;
  payload?: Record<string, unknown>;
};

type Listener = (envelope: RealtimeEnvelope) => void;

const recentEventIds = new Set<string>();
const MAX_DEDUPED = 500;

function rememberEventId(eventId: string): boolean {
  if (recentEventIds.has(eventId)) {
    return false;
  }
  recentEventIds.add(eventId);
  if (recentEventIds.size > MAX_DEDUPED) {
    const first = recentEventIds.values().next().value;
    if (first != null) {
      recentEventIds.delete(first);
    }
  }
  return true;
}

function resolveRealtimeUrl(token: string): string | null {
  const extra = Constants.expoConfig?.extra as { realtimeUrl?: string } | undefined;
  const base = extra?.realtimeUrl ?? REALTIME_URL;
  if (!base || typeof WebSocket === "undefined") {
    return null;
  }
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}access_token=${encodeURIComponent(token)}`;
}

/**
 * Subscribe to the local realtime hub. Deduplicates by event_id.
 * Returns an unsubscribe function.
 */
export function subscribeRealtime(listener: Listener): () => void {
  const token = getLiveAccessToken();
  if (!token) {
    return () => undefined;
  }
  const url = resolveRealtimeUrl(token);
  if (!url) {
    return () => undefined;
  }

  let closed = false;
  let socket: WebSocket | null = null;
  try {
    socket = new WebSocket(url);
  } catch {
    return () => undefined;
  }

  socket.onmessage = (event) => {
    if (closed) {
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(String(event.data));
    } catch {
      return;
    }
    if (parsed == null || typeof parsed !== "object") {
      return;
    }
    const envelope = parsed as RealtimeEnvelope;
    const eventId = envelope.event_id ?? (envelope.payload?.event_id as string | undefined);
    if (typeof eventId === "string" && eventId.length > 0) {
      if (!rememberEventId(eventId)) {
        return;
      }
      void fetch(`${API_BASE_URL}/v1/events/${eventId}/ack`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: "{}",
      }).catch(() => undefined);
    }
    listener(envelope);
  };

  return () => {
    closed = true;
    socket?.close();
  };
}
