/**
 * Pure notification Zod contracts (no Expo / RN imports).
 * Never log response bodies — they may include deep links or actor data.
 */

import { z } from "zod";

export const NOTIFICATION_CATEGORIES = [
  "messages",
  "calling_cards",
  "stories",
  "venue_management",
  "account",
] as const;

export type NotificationCategory = (typeof NOTIFICATION_CATEGORIES)[number];

export const NOTIFICATION_TYPES = [
  "calling_card.received",
  "calling_card.accepted",
  "message.received",
  "story.published",
  "story.rejected",
  "story.failed",
  "venue_claim.approved",
  "venue_claim.rejected",
  "organization.invitation.received",
  "system.account_notice",
] as const;

export type NotificationType = (typeof NOTIFICATION_TYPES)[number];

function logSchemaError(context: string, error: unknown): void {
  if (typeof __DEV__ !== "undefined" && __DEV__ && typeof console !== "undefined") {
    const message = error instanceof Error ? error.message : "schema_error";
    console.warn(`[notifications] ${context}: ${message}`);
  }
}

export function parseNotificationPayload<T>(
  schema: z.ZodType<T>,
  data: unknown,
  context: string,
): T {
  try {
    return schema.parse(data);
  } catch (error) {
    logSchemaError(context, error);
    throw error;
  }
}

export const notificationActorSchema = z
  .object({
    id: z.string().uuid().nullable().optional(),
    handle: z.string().nullable().optional(),
    display_name: z.string().nullable().optional(),
    label: z.string(),
  })
  .strict();

export const notificationItemSchema = z
  .object({
    notification_id: z.string().uuid(),
    notification_type: z.string(),
    category: z.string(),
    title: z.string(),
    body: z.string(),
    deep_link: z.string().nullable().optional(),
    occurrence_count: z.number().int().positive(),
    priority: z.enum(["normal", "high"]),
    read: z.boolean(),
    actor: notificationActorSchema.nullable().optional(),
    venue_id: z.string().uuid().nullable().optional(),
    conversation_id: z.string().uuid().nullable().optional(),
    calling_card_id: z.string().uuid().nullable().optional(),
    story_id: z.string().uuid().nullable().optional(),
    organization_id: z.string().uuid().nullable().optional(),
    venue_claim_id: z.string().uuid().nullable().optional(),
    latest_event_at: z.string(),
    created_at: z.string(),
  })
  .strict();

export type NotificationItem = z.infer<typeof notificationItemSchema>;

export const notificationListSchema = z
  .object({
    items: z.array(notificationItemSchema),
    next_cursor: z.string().nullable(),
  })
  .strict();

export type NotificationListPage = z.infer<typeof notificationListSchema>;

export const unreadCountSchema = z
  .object({
    total: z.number().int().nonnegative(),
    by_category: z.record(z.string(), z.number().int().nonnegative()),
  })
  .strict();

export type UnreadCount = z.infer<typeof unreadCountSchema>;

export const readNotificationSchema = z
  .object({
    notification_id: z.string().uuid(),
    read: z.literal(true),
    read_at: z.string(),
  })
  .strict();

export const readAllNotificationsSchema = z
  .object({
    changed_count: z.number().int().nonnegative(),
  })
  .strict();

export const dismissNotificationSchema = z
  .object({
    notification_id: z.string().uuid(),
    dismissed: z.literal(true),
    dismissed_at: z.string(),
  })
  .strict();

export const preferenceItemSchema = z
  .object({
    category: z.string(),
    in_app_enabled: z.boolean(),
    push_enabled: z.boolean(),
  })
  .strict();

export const preferenceListSchema = z
  .object({
    items: z.array(preferenceItemSchema),
  })
  .strict();

export type PreferenceList = z.infer<typeof preferenceListSchema>;

export const preferencePatchRequestSchema = z
  .object({
    items: z
      .array(
        z
          .object({
            category: z.string(),
            in_app_enabled: z.boolean().optional(),
            push_enabled: z.boolean().optional(),
          })
          .strict(),
      )
      .min(1),
  })
  .strict();

export const pushTokenRegisterResponseSchema = z
  .object({
    registered: z.literal(true),
    provider: z.literal("expo"),
    device_id: z.string().uuid(),
  })
  .strict();

export const pushTokenDeleteResponseSchema = z
  .object({
    disabled: z.literal(true),
    device_id: z.string().uuid(),
  })
  .strict();

export const realtimeTicketSchema = z
  .object({
    ticket: z.string().min(16),
    expires_in_seconds: z.number().int().positive(),
    purpose: z.enum(["notifications", "calling_cards"]),
    websocket_path: z.enum(["/v1/realtime/notifications", "/v1/realtime/ws"]),
  })
  .strict();

export type RealtimeTicket = z.infer<typeof realtimeTicketSchema>;

export const realtimeTicketRequestSchema = z
  .object({
    purpose: z.enum(["notifications", "calling_cards"]),
  })
  .strict();

export const realtimeAuthenticateFrameSchema = z
  .object({
    type: z.literal("authenticate"),
    ticket: z.string().min(16),
  })
  .strict();

export const realtimeUnreadPayloadSchema = z
  .object({
    total: z.number().int().nonnegative(),
    by_category: z.record(z.string(), z.number().int().nonnegative()).optional(),
  })
  .strict();

export const realtimeNotificationHintPayloadSchema = z
  .object({
    notification_id: z.string().uuid(),
    notification_type: z.string().optional(),
    category: z.string().optional(),
    occurrence_count: z.number().int().positive().optional(),
    deep_link: z.string().nullable().optional(),
    latest_event_at: z.string().optional(),
  })
  .strict();

export const realtimeEventSchema = z.discriminatedUnion("type", [
  z
    .object({
      type: z.literal("notification.created"),
      payload: realtimeNotificationHintPayloadSchema,
    })
    .strict(),
  z
    .object({
      type: z.literal("notification.updated"),
      payload: realtimeNotificationHintPayloadSchema,
    })
    .strict(),
  z
    .object({
      type: z.literal("notification.read"),
      payload: z.object({ notification_id: z.string().uuid() }).strict(),
    })
    .strict(),
  z
    .object({
      type: z.literal("notification.dismissed"),
      payload: z.object({ notification_id: z.string().uuid() }).strict(),
    })
    .strict(),
  z
    .object({
      type: z.literal("unread_count.changed"),
      payload: realtimeUnreadPayloadSchema,
    })
    .strict(),
  z.object({ type: z.literal("pong") }).strict(),
]);

export type RealtimeNotificationEvent = z.infer<typeof realtimeEventSchema>;

/** Reject payloads that smuggle sensitive fields into client consumption. */
export const FORBIDDEN_NOTIFICATION_FIELDS = [
  "push_token",
  "token_hash",
  "signed_url",
  "object_key",
  "quarantine_object_key",
  "invitation_token",
  "evidence",
  "message_body",
  "storage_key",
] as const;
