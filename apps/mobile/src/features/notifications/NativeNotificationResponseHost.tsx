/**
 * Handle OS notification taps → validated deep-link navigation (once).
 */

import { useRouter } from "expo-router";
import * as React from "react";
import { AppState } from "react-native";

import { useAuth } from "@/auth/AuthProvider";
import { deepLinkToHref, parseNotificationDeepLink } from "./deepLinks";
import {
  clearHandledNotificationResponses,
  markNotificationResponseHandled,
  wasNotificationResponseHandled,
} from "./notificationResponseDedupe";
import { useNotificationsOptional } from "./NotificationsProvider";

type NotificationsModule = typeof import("expo-notifications");

function extractDeepLink(data: unknown): string | null {
  if (!data || typeof data !== "object") {
    return null;
  }
  const record = data as Record<string, unknown>;
  const candidates = [record.deep_link, record.deepLink, record.url];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

export function NativeNotificationResponseHost() {
  const auth = useAuth();
  const router = useRouter();
  const notifications = useNotificationsOptional();
  const pendingRef = React.useRef<string | null>(null);

  const navigateSafe = React.useCallback(
    (rawLink: string, responseId: string) => {
      if (wasNotificationResponseHandled(responseId)) {
        return;
      }
      const parsed = parseNotificationDeepLink(rawLink);
      if (!parsed) {
        return;
      }
      markNotificationResponseHandled(responseId);
      pendingRef.current = null;
      notifications?.refreshInboxHints();
      router.push(deepLinkToHref(parsed) as never);
    },
    [notifications, router],
  );

  React.useEffect(() => {
    if (auth.status === "unauthenticated") {
      pendingRef.current = null;
      clearHandledNotificationResponses();
    }
  }, [auth.status]);

  React.useEffect(() => {
    if (auth.status !== "authenticated" || !pendingRef.current) {
      return;
    }
    const raw = pendingRef.current;
    navigateSafe(raw, `pending:${raw}`);
  }, [auth.status, navigateSafe]);

  React.useEffect(() => {
    let subscription: { remove: () => void } | null = null;
    let cancelled = false;

    (async () => {
      let Notifications: NotificationsModule | null = null;
      try {
        Notifications = await import("expo-notifications");
      } catch {
        return;
      }
      if (cancelled || !Notifications) {
        return;
      }

      const last = await Notifications.getLastNotificationResponseAsync();
      if (last && !cancelled) {
        const responseId = last.notification.request.identifier || "cold-start";
        const raw = extractDeepLink(last.notification.request.content.data);
        if (raw) {
          if (auth.status === "authenticated") {
            navigateSafe(raw, responseId);
          } else {
            pendingRef.current = raw;
          }
        }
      }

      subscription = Notifications.addNotificationResponseReceivedListener((response) => {
        const responseId = response.notification.request.identifier || String(Date.now());
        const raw = extractDeepLink(response.notification.request.content.data);
        if (!raw) {
          return;
        }
        if (auth.status !== "authenticated") {
          pendingRef.current = raw;
          return;
        }
        navigateSafe(raw, responseId);
      });
    })().catch(() => undefined);

    return () => {
      cancelled = true;
      subscription?.remove();
    };
  }, [auth.status, navigateSafe]);

  React.useEffect(() => {
    const sub = AppState.addEventListener("change", (next) => {
      if (next === "active") {
        notifications?.refreshUnread();
      }
    });
    return () => sub.remove();
  }, [notifications]);

  return null;
}
