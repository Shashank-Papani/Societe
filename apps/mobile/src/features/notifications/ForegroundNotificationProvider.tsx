import * as React from "react";
import { AppState } from "react-native";

import { newIdempotencyKey } from "@/features/connect/api";
import { subscribeRealtime } from "@/realtime/client";

export type CallingCardNotification = {
  id: string;
  kind: "calling_card";
  eventId: string;
  callingCardId: string;
  displayName: string;
  handle?: string | null;
  avatarUrl?: string | null;
  venueName?: string | null;
  reasonCode?: string | null;
  customMessage?: string | null;
};

export type MessageNotification = {
  id: string;
  kind: "message";
  eventId: string;
  conversationId: string;
  displayName: string;
  handle?: string | null;
  avatarUrl?: string | null;
  preview: string;
  previewHidden?: boolean;
};

export type ForegroundNotification = CallingCardNotification | MessageNotification;

type Ctx = {
  active: ForegroundNotification | null;
  enqueue: (notification: ForegroundNotification) => void;
  dismiss: (id: string) => void;
  setActiveConversationId: (id: string | null) => void;
  respondCallingCard: (
    callingCardId: string,
    decision: "accept" | "decline",
  ) => Promise<void>;
};

const ForegroundNotificationContext = React.createContext<Ctx | null>(null);

function payloadString(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value : null;
}

export function ForegroundNotificationProvider({ children }: { children: React.ReactNode }) {
  const [queue, setQueue] = React.useState<ForegroundNotification[]>([]);
  const [activeConversationId, setActiveConversationId] = React.useState<string | null>(null);
  const seenEventIds = React.useRef(new Set<string>());
  const appState = React.useRef(AppState.currentState);

  React.useEffect(() => {
    const sub = AppState.addEventListener("change", (next) => {
      appState.current = next;
    });
    return () => sub.remove();
  }, []);

  const enqueue = React.useCallback(
    (notification: ForegroundNotification) => {
      if (seenEventIds.current.has(notification.eventId)) {
        return;
      }
      seenEventIds.current.add(notification.eventId);
      if (
        notification.kind === "message" &&
        activeConversationId &&
        notification.conversationId === activeConversationId
      ) {
        return;
      }
      setQueue((current) => {
        if (current.some((item) => item.id === notification.id)) {
          return current;
        }
        // Calling Cards take priority — insert ahead of message banners.
        if (notification.kind === "calling_card") {
          return [notification, ...current.filter((item) => item.kind !== "calling_card")];
        }
        return [...current, notification];
      });
    },
    [activeConversationId],
  );

  const dismiss = React.useCallback((id: string) => {
    setQueue((current) => current.filter((item) => item.id !== id));
  }, []);

  const respondCallingCard = React.useCallback(
    async (callingCardId: string, decision: "accept" | "decline") => {
      const { enqueueRespondCallingCard, flushOfflineQueue } = await import(
        "@/features/connect/offlineQueue"
      );
      const key = newIdempotencyKey();
      await enqueueRespondCallingCard({
        callingCardId,
        decision,
        action: decision === "accept" ? "accept_only" : null,
        idempotencyKey: key,
      });
      await flushOfflineQueue();
      setQueue((current) =>
        current.filter(
          (item) => !(item.kind === "calling_card" && item.callingCardId === callingCardId),
        ),
      );
    },
    [],
  );

  React.useEffect(() => {
    return subscribeRealtime((envelope) => {
      if (appState.current !== "active") {
        return;
      }
      const eventId = envelope.event_id ?? `${envelope.event_type}:${Date.now()}`;
      const payload = (envelope.payload ?? {}) as Record<string, unknown>;
      const type = envelope.event_type ?? "";

      if (type === "calling_card.created") {
        const callingCardId = payloadString(payload, "calling_card_id");
        if (!callingCardId) {
          return;
        }
        enqueue({
          id: `cc:${callingCardId}`,
          kind: "calling_card",
          eventId,
          callingCardId,
          displayName: payloadString(payload, "sender_display_name") ?? "Someone nearby",
          handle: payloadString(payload, "sender_handle"),
          venueName: payloadString(payload, "venue_name"),
          reasonCode: payloadString(payload, "reason_code"),
          customMessage: payloadString(payload, "custom_message"),
        });
        return;
      }

      if (type === "message.created") {
        const conversationId = payloadString(payload, "conversation_id");
        const messageId = payloadString(payload, "message_id") ?? eventId;
        if (!conversationId) {
          return;
        }
        enqueue({
          id: `msg:${messageId}`,
          kind: "message",
          eventId,
          conversationId,
          displayName: payloadString(payload, "sender_display_name") ?? "New message",
          handle: payloadString(payload, "sender_handle"),
          preview: payloadString(payload, "preview") ?? "New message",
          previewHidden: payload.preview_hidden === true,
        });
      }
    });
  }, [enqueue]);

  const active = queue[0] ?? null;
  const value: Ctx = {
    active,
    enqueue,
    dismiss,
    setActiveConversationId,
    respondCallingCard,
  };

  return (
    <ForegroundNotificationContext.Provider value={value}>
      {children}
    </ForegroundNotificationContext.Provider>
  );
}

export function useForegroundNotifications(): Ctx {
  const ctx = React.useContext(ForegroundNotificationContext);
  if (!ctx) {
    throw new Error("useForegroundNotifications requires ForegroundNotificationProvider");
  }
  return ctx;
}
