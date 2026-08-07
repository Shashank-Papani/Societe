/**
 * Secure notifications WebSocket client (Phase 9A ticket auth).
 *
 * Flow:
 * 1. POST /v1/realtime/tickets
 * 2. open WS /v1/realtime/notifications (NO query ticket / access_token)
 * 3. first frame: { type: "authenticate", ticket }
 * 4. discard ticket reference
 *
 * Never log the ticket.
 */

import Constants from "expo-constants";

import { API_BASE_URL } from "@/api/client";
import { createRealtimeTicket } from "./api";
import { realtimeBackoffMs } from "./notificationHelpers";
import {
  parseNotificationPayload,
  realtimeEventSchema,
  type RealtimeNotificationEvent,
} from "./notificationSchemas";
import { notificationsWsUrlFromApiBase } from "./realtimeHelpers";

export type NotificationsRealtimeListener = (event: RealtimeNotificationEvent) => void;

export {
  assertSafeNotificationsWsUrl,
  buildAuthenticateFrame,
  notificationsWsUrlFromApiBase,
} from "./realtimeHelpers";

type Extra = { apiBaseUrl?: string; realtimeUrl?: string } | undefined;

function notificationsWsUrl(): string {
  const extra = Constants.expoConfig?.extra as Extra;
  const apiBase = extra?.apiBaseUrl ?? API_BASE_URL;
  return notificationsWsUrlFromApiBase(apiBase);
}

export class NotificationsRealtimeClient {
  private socket: WebSocket | null = null;
  private listener: NotificationsRealtimeListener | null = null;
  private onConnected: (() => void) | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private stopped = true;
  private intentionalClose = false;

  start(
    listener: NotificationsRealtimeListener,
    onConnected?: () => void,
  ): void {
    this.listener = listener;
    this.onConnected = onConnected ?? null;
    this.stopped = false;
    this.intentionalClose = false;
    this.attempt = 0;
    void this.connect();
  }

  /** Force a fresh ticket + socket (e.g. app foreground while disconnected). */
  reconnectNow(): void {
    if (this.stopped) {
      return;
    }
    this.clearReconnect();
    this.intentionalClose = false;
    void this.connect();
  }

  isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  stop(): void {
    this.stopped = true;
    this.intentionalClose = true;
    this.listener = null;
    this.onConnected = null;
    this.clearHeartbeat();
    this.clearReconnect();
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        // ignore
      }
      this.socket = null;
    }
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.intentionalClose) {
      return;
    }
    this.clearReconnect();
    this.attempt += 1;
    const delay = realtimeBackoffMs(this.attempt);
    this.reconnectTimer = setTimeout(() => {
      void this.connect();
    }, delay);
  }

  private async connect(): Promise<void> {
    if (this.stopped) {
      return;
    }
    this.clearHeartbeat();
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        // ignore
      }
      this.socket = null;
    }

    let ticket: string;
    try {
      const issued = await createRealtimeTicket("notifications");
      ticket = issued.ticket;
    } catch {
      this.scheduleReconnect();
      return;
    }

    const url = notificationsWsUrl();
    if (url.includes("ticket=") || url.includes("access_token=")) {
      // Hard guard — never connect with secrets in the URL.
      this.scheduleReconnect();
      return;
    }

    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      if (this.stopped || this.socket !== socket) {
        return;
      }
      // Authenticate immediately; discard local ticket reference after send.
      const frame = { type: "authenticate" as const, ticket };
      ticket = "";
      try {
        socket.send(JSON.stringify(frame));
      } catch {
        socket.close();
        return;
      }
      this.attempt = 0;
      this.heartbeatTimer = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send("ping");
        }
      }, 25_000);
      this.onConnected?.();
    };

    socket.onmessage = (event) => {
      if (this.stopped || !this.listener) {
        return;
      }
      let parsed: unknown;
      try {
        parsed = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      } catch {
        return;
      }
      try {
        const msg = parseNotificationPayload(
          realtimeEventSchema,
          parsed,
          "realtime-event",
        );
        if (msg.type === "pong") {
          return;
        }
        this.listener(msg);
      } catch {
        // Malformed events are ignored safely.
      }
    };

    socket.onerror = () => {
      // onclose handles reconnect
    };

    socket.onclose = () => {
      this.clearHeartbeat();
      if (this.socket === socket) {
        this.socket = null;
      }
      if (!this.intentionalClose && !this.stopped) {
        this.scheduleReconnect();
      }
    };
  }
}
