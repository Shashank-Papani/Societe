/**
 * Notification REST client — Phase 9A contracts via apiFetch + Zod.
 */

import { apiFetch } from "@/api/client";

import {
  dismissNotificationSchema,
  notificationListSchema,
  parseNotificationPayload,
  preferenceListSchema,
  preferencePatchRequestSchema,
  pushTokenDeleteResponseSchema,
  pushTokenRegisterResponseSchema,
  readAllNotificationsSchema,
  readNotificationSchema,
  realtimeTicketSchema,
  unreadCountSchema,
  type NotificationListPage,
  type PreferenceList,
  type RealtimeTicket,
  type UnreadCount,
} from "./notificationSchemas";

export type ListNotificationsParams = {
  cursor?: string | null;
  limit?: number;
  unreadOnly?: boolean;
  category?: string | null;
};

export async function fetchNotifications(
  params: ListNotificationsParams = {},
): Promise<NotificationListPage> {
  const query = new URLSearchParams();
  if (params.cursor) {
    query.set("cursor", params.cursor);
  }
  if (params.limit != null) {
    query.set("limit", String(params.limit));
  }
  if (params.unreadOnly) {
    query.set("unread_only", "true");
  }
  if (params.category) {
    query.set("category", params.category);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const envelope = await apiFetch<unknown>(`/v1/notifications${suffix}`);
  return parseNotificationPayload(notificationListSchema, envelope.data, "list");
}

export async function fetchUnreadCount(): Promise<UnreadCount> {
  const envelope = await apiFetch<unknown>("/v1/notifications/unread-count");
  return parseNotificationPayload(unreadCountSchema, envelope.data, "unread-count");
}

export async function markNotificationRead(notificationId: string) {
  const envelope = await apiFetch<unknown>(`/v1/notifications/${notificationId}/read`, {
    method: "POST",
  });
  return parseNotificationPayload(readNotificationSchema, envelope.data, "read");
}

export async function markAllNotificationsRead(category?: string | null) {
  const body =
    category != null && category !== ""
      ? JSON.stringify({ category })
      : JSON.stringify({});
  const envelope = await apiFetch<unknown>("/v1/notifications/read-all", {
    method: "POST",
    body,
  });
  return parseNotificationPayload(readAllNotificationsSchema, envelope.data, "read-all");
}

export async function dismissNotification(notificationId: string) {
  const envelope = await apiFetch<unknown>(`/v1/notifications/${notificationId}`, {
    method: "DELETE",
  });
  return parseNotificationPayload(dismissNotificationSchema, envelope.data, "dismiss");
}

export async function fetchNotificationPreferences(): Promise<PreferenceList> {
  const envelope = await apiFetch<unknown>("/v1/me/notification-preferences");
  return parseNotificationPayload(preferenceListSchema, envelope.data, "preferences");
}

export async function patchNotificationPreferences(
  items: {
    category: string;
    in_app_enabled?: boolean;
    push_enabled?: boolean;
  }[],
): Promise<PreferenceList> {
  const body = preferencePatchRequestSchema.parse({ items });
  const envelope = await apiFetch<unknown>("/v1/me/notification-preferences", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return parseNotificationPayload(preferenceListSchema, envelope.data, "preferences-patch");
}

export async function registerExpoPushToken(deviceId: string, token: string) {
  const envelope = await apiFetch<unknown>(`/v1/me/devices/${deviceId}/push-token`, {
    method: "PUT",
    body: JSON.stringify({ provider: "expo", token }),
  });
  return parseNotificationPayload(
    pushTokenRegisterResponseSchema,
    envelope.data,
    "push-register",
  );
}

export async function unregisterPushToken(deviceId: string) {
  const envelope = await apiFetch<unknown>(`/v1/me/devices/${deviceId}/push-token`, {
    method: "DELETE",
  });
  return parseNotificationPayload(
    pushTokenDeleteResponseSchema,
    envelope.data,
    "push-unregister",
  );
}

export async function createRealtimeTicket(
  purpose: "notifications" | "calling_cards" = "notifications",
): Promise<RealtimeTicket> {
  const envelope = await apiFetch<unknown>("/v1/realtime/tickets", {
    method: "POST",
    body: JSON.stringify({ purpose }),
  });
  const parsed = parseNotificationPayload(realtimeTicketSchema, envelope.data, "realtime-ticket");
  const expectedPath =
    purpose === "notifications" ? "/v1/realtime/notifications" : "/v1/realtime/ws";
  if (parsed.purpose !== purpose || parsed.websocket_path !== expectedPath) {
    throw new Error("realtime_ticket_purpose_mismatch");
  }
  return parsed;
}
