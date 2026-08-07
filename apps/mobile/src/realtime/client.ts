/**
 * Calling Card / user-hub realtime client.
 *
 * Secure flow:
 * 1. POST /v1/realtime/tickets { purpose: "calling_cards" }
 * 2. open WS /v1/realtime/ws (NO query ticket / access_token)
 * 3. first frame: { type: "authenticate", ticket }
 * 4. discard ticket reference
 *
 * Never log the ticket or access token.
 */

import Constants from "expo-constants";

import { API_BASE_URL, REALTIME_URL, apiFetch } from "@/api/client";
import { getLiveAccessToken } from "@/auth/AuthProvider";
import {
  assertSafeCallingCardsWsUrl,
  callingCardsWsUrlFromApiBase,
} from "./urlHelpers";

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

function resolveCleanRealtimeUrl(): string | null {
  const extra = Constants.expoConfig?.extra as
    | { realtimeUrl?: string; apiBaseUrl?: string }
    | undefined;
  if (typeof WebSocket === "undefined") {
    return null;
  }
  // Prefer deriving from API base so we never inherit a stale query string.
  const apiBase = extra?.apiBaseUrl ?? API_BASE_URL;
  const derived = callingCardsWsUrlFromApiBase(apiBase);
  if (assertSafeCallingCardsWsUrl(derived)) {
    return derived;
  }
  const configured = extra?.realtimeUrl ?? REALTIME_URL;
  if (!configured) {
    return null;
  }
  // Strip any accidental query secrets from configured URL.
  try {
    const parsed = new URL(configured);
    parsed.search = "";
    parsed.hash = "";
    const cleaned = parsed.toString().replace(/\/$/, "");
    return assertSafeCallingCardsWsUrl(cleaned) ? cleaned : null;
  } catch {
    return null;
  }
}

type TicketResponse = {
  ticket: string;
  expires_in_seconds: number;
  purpose: "calling_cards";
  websocket_path: "/v1/realtime/ws";
};

async function issueCallingCardsTicket(): Promise<string> {
  const envelope = await apiFetch<TicketResponse>("/v1/realtime/tickets", {
    method: "POST",
    body: JSON.stringify({ purpose: "calling_cards" }),
  });
  const ticket = envelope.data.ticket;
  if (!ticket || ticket.length < 16) {
    throw new Error("invalid_realtime_ticket");
  }
  if (envelope.data.websocket_path !== "/v1/realtime/ws") {
    throw new Error("unexpected_websocket_path");
  }
  return ticket;
}

function backoffMs(attempt: number): number {
  const capped = Math.min(30_000, 1000 * 2 ** Math.max(0, attempt - 1));
  return Math.floor(Math.random() * (capped + 1));
}

/**
 * Subscribe to the local realtime hub (Calling Cards / messages).
 * Deduplicates by event_id. Reconnects with a fresh ticket.
 * Returns an unsubscribe function that prevents further reconnects.
 */
export function subscribeRealtime(listener: Listener): () => void {
  if (!getLiveAccessToken()) {
    return () => undefined;
  }

  let closed = false;
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;

  const clearReconnect = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (closed || !getLiveAccessToken()) {
      return;
    }
    clearReconnect();
    attempt += 1;
    reconnectTimer = setTimeout(() => {
      void connect();
    }, backoffMs(attempt));
  };

  const connect = async () => {
    if (closed || !getLiveAccessToken()) {
      return;
    }
    if (socket) {
      try {
        socket.close();
      } catch {
        // ignore
      }
      socket = null;
    }

    let ticket: string;
    try {
      ticket = await issueCallingCardsTicket();
    } catch {
      scheduleReconnect();
      return;
    }

    const url = resolveCleanRealtimeUrl();
    if (!url || url.includes("ticket=") || url.includes("access_token=")) {
      scheduleReconnect();
      return;
    }

    let next: WebSocket;
    try {
      next = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }
    socket = next;

    next.onopen = () => {
      if (closed || socket !== next) {
        return;
      }
      const frame = { type: "authenticate" as const, ticket };
      ticket = "";
      try {
        next.send(JSON.stringify(frame));
      } catch {
        next.close();
        return;
      }
      attempt = 0;
    };

    next.onmessage = (event) => {
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
      // Ignore the post-auth subscription hint for banner listeners.
      if (envelope.event_type == null && (envelope as { type?: string }).type === "subscribed") {
        return;
      }
      const eventId =
        envelope.event_id ?? (envelope.payload?.event_id as string | undefined);
      if (typeof eventId === "string" && eventId.length > 0) {
        if (!rememberEventId(eventId)) {
          return;
        }
        const accessToken = getLiveAccessToken();
        if (accessToken) {
          void fetch(`${API_BASE_URL}/v1/events/${eventId}/ack`, {
            method: "POST",
            headers: {
              Authorization: `Bearer ${accessToken}`,
              "Content-Type": "application/json",
            },
            body: "{}",
          }).catch(() => undefined);
        }
      }
      listener(envelope);
    };

    next.onclose = () => {
      if (socket === next) {
        socket = null;
      }
      if (!closed) {
        scheduleReconnect();
      }
    };

    next.onerror = () => {
      // onclose handles reconnect
    };
  };

  void connect();

  return () => {
    closed = true;
    clearReconnect();
    if (socket) {
      try {
        socket.close();
      } catch {
        // ignore
      }
      socket = null;
    }
  };
}
