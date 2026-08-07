/**
 * Root notifications lifecycle: unread query, realtime hints, AppState refresh,
 * push registration reconciliation, logout isolation.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { AppState } from "react-native";

import { useAuth } from "@/auth/AuthProvider";
import { fetchUnreadCount } from "./api";
import {
  configureForegroundNotificationHandler,
  registerCurrentDevicePushToken,
} from "./pushRegistration";
import {
  NotificationsRealtimeClient,
  type NotificationsRealtimeListener,
} from "./realtime";
import type { RealtimeNotificationEvent } from "./notificationSchemas";

type NotificationsContextValue = {
  unreadTotal: number;
  isUnreadLoading: boolean;
  refreshUnread: () => void;
  refreshInboxHints: () => void;
};

const NotificationsContext = React.createContext<NotificationsContextValue | null>(null);

export function useNotifications(): NotificationsContextValue {
  const ctx = React.useContext(NotificationsContext);
  if (!ctx) {
    throw new Error("useNotifications must be used within NotificationsProvider");
  }
  return ctx;
}

/** Optional hook when provider may be absent in tests. */
export function useNotificationsOptional(): NotificationsContextValue | null {
  return React.useContext(NotificationsContext);
}

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const clientRef = React.useRef<NotificationsRealtimeClient | null>(null);
  const authenticated = auth.status === "authenticated";

  const unreadQuery = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: fetchUnreadCount,
    enabled: authenticated,
    staleTime: 15_000,
    retry: 1,
  });

  const refreshUnread = React.useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["notifications", "unread-count"] });
  }, [queryClient]);

  const refreshInboxHints = React.useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["notifications", "list"] });
    void queryClient.invalidateQueries({ queryKey: ["notifications", "unread-count"] });
  }, [queryClient]);

  const onRealtimeEvent = React.useCallback<NotificationsRealtimeListener>(
    (event: RealtimeNotificationEvent) => {
      switch (event.type) {
        case "unread_count.changed":
          queryClient.setQueryData(["notifications", "unread-count"], (prev: unknown) => {
            const total = event.payload.total;
            if (
              prev &&
              typeof prev === "object" &&
              "by_category" in prev &&
              event.payload.by_category
            ) {
              return { total, by_category: event.payload.by_category };
            }
            if (prev && typeof prev === "object" && "by_category" in prev) {
              return {
                total,
                by_category: (prev as { by_category: Record<string, number> }).by_category,
              };
            }
            return { total, by_category: event.payload.by_category ?? {} };
          });
          break;
        case "notification.created":
        case "notification.updated":
        case "notification.read":
        case "notification.dismissed":
          void queryClient.invalidateQueries({ queryKey: ["notifications", "list"] });
          void queryClient.invalidateQueries({ queryKey: ["notifications", "unread-count"] });
          break;
        default:
          break;
      }
    },
    [queryClient],
  );

  React.useEffect(() => {
    if (!authenticated) {
      clientRef.current?.stop();
      clientRef.current = null;
      return;
    }
    const client = new NotificationsRealtimeClient();
    clientRef.current = client;
    client.start(onRealtimeEvent, refreshInboxHints);
    void configureForegroundNotificationHandler();
    return () => {
      client.stop();
      if (clientRef.current === client) {
        clientRef.current = null;
      }
    };
  }, [authenticated, onRealtimeEvent, refreshInboxHints]);

  React.useEffect(() => {
    if (!authenticated) {
      return;
    }
    const sub = AppState.addEventListener("change", (next) => {
      if (next !== "active") {
        return;
      }
      refreshInboxHints();
      const client = clientRef.current;
      if (!client) {
        const nextClient = new NotificationsRealtimeClient();
        clientRef.current = nextClient;
        nextClient.start(onRealtimeEvent, refreshInboxHints);
      } else if (!client.isOpen()) {
        client.reconnectNow();
      }
      void registerCurrentDevicePushToken();
    });
    return () => sub.remove();
  }, [authenticated, onRealtimeEvent, refreshInboxHints]);

  React.useEffect(() => {
    if (!authenticated) {
      return;
    }
    let subscription: { remove: () => void } | null = null;
    let cancelled = false;
    (async () => {
      try {
        const Notifications = await import("expo-notifications");
        if (cancelled) {
          return;
        }
        subscription = Notifications.addNotificationReceivedListener(() => {
          // Inbox remains authoritative — refresh, do not invent local rows.
          refreshInboxHints();
        });
      } catch {
        // expo-notifications unavailable (web / incomplete native build).
      }
    })().catch(() => undefined);
    return () => {
      cancelled = true;
      subscription?.remove();
    };
  }, [authenticated, refreshInboxHints]);

  const value = React.useMemo<NotificationsContextValue>(
    () => ({
      unreadTotal: unreadQuery.data?.total ?? 0,
      isUnreadLoading: unreadQuery.isLoading,
      refreshUnread,
      refreshInboxHints,
    }),
    [refreshInboxHints, refreshUnread, unreadQuery.data?.total, unreadQuery.isLoading],
  );

  return (
    <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
  );
}
