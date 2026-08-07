import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  FORBIDDEN_NOTIFICATION_FIELDS,
  dismissNotificationSchema,
  notificationItemSchema,
  notificationListSchema,
  preferenceListSchema,
  pushTokenRegisterResponseSchema,
  readAllNotificationsSchema,
  readNotificationSchema,
  realtimeAuthenticateFrameSchema,
  realtimeEventSchema,
  realtimeTicketSchema,
  unreadCountSchema,
} from "./notificationSchemas.ts";
import {
  actorDisplayLabel,
  clampUnreadTotal,
  formatUnreadBadge,
  isMandatoryInAppCategory,
  markAllNotificationsRead,
  markNotificationReadInList,
  mergeNotificationPages,
  notificationRowAccessibilityLabel,
  relativeTimestamp,
  removeNotificationItem,
  unreadBadgeAccessibilityLabel,
  upsertNotificationItem,
} from "./notificationHelpers.ts";
import type { NotificationItem } from "./notificationSchemas.ts";

const nid = "11111111-1111-4111-8111-111111111111";
const actorId = "22222222-2222-4222-8222-222222222222";

function sampleItem(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return notificationItemSchema.parse({
    notification_id: nid,
    notification_type: "message.received",
    category: "messages",
    title: "New message",
    body: "Hey there",
    deep_link: `societe://conversation/${nid}`,
    occurrence_count: 1,
    priority: "normal",
    read: false,
    actor: {
      id: actorId,
      handle: "alpha",
      display_name: "Alpha",
      label: "Alpha",
    },
    venue_id: null,
    conversation_id: nid,
    calling_card_id: null,
    story_id: null,
    organization_id: null,
    venue_claim_id: null,
    latest_event_at: "2026-07-29T20:00:00Z",
    created_at: "2026-07-29T19:00:00Z",
    ...overrides,
  });
}

describe("Notification contract schemas", () => {
  it("parses a notification item", () => {
    const item = sampleItem();
    assert.equal(item.notification_id, nid);
    assert.equal(item.read, false);
  });

  it("parses a notification page", () => {
    const page = notificationListSchema.parse({
      items: [sampleItem()],
      next_cursor: "cursor-1",
    });
    assert.equal(page.items.length, 1);
    assert.equal(page.next_cursor, "cursor-1");
  });

  it("parses unread count", () => {
    const unread = unreadCountSchema.parse({
      total: 3,
      by_category: { messages: 2, calling_cards: 1 },
    });
    assert.equal(unread.total, 3);
  });

  it("parses preferences", () => {
    const prefs = preferenceListSchema.parse({
      items: [
        { category: "messages", in_app_enabled: true, push_enabled: false },
        { category: "account", in_app_enabled: true, push_enabled: true },
      ],
    });
    assert.equal(prefs.items.length, 2);
  });

  it("parses push registration response", () => {
    const res = pushTokenRegisterResponseSchema.parse({
      registered: true,
      provider: "expo",
      device_id: nid,
    });
    assert.equal(res.provider, "expo");
  });

  it("parses realtime ticket response", () => {
    const ticket = realtimeTicketSchema.parse({
      ticket: "t".repeat(32),
      expires_in_seconds: 30,
      purpose: "notifications",
      websocket_path: "/v1/realtime/notifications",
    });
    assert.equal(ticket.websocket_path, "/v1/realtime/notifications");
    assert.equal(ticket.purpose, "notifications");
  });

  it("parses realtime authenticate frame", () => {
    const frame = realtimeAuthenticateFrameSchema.parse({
      type: "authenticate",
      ticket: "t".repeat(32),
    });
    assert.equal(frame.type, "authenticate");
  });

  it("parses realtime event envelopes", () => {
    const created = realtimeEventSchema.parse({
      type: "notification.created",
      payload: { notification_id: nid, category: "messages" },
    });
    assert.equal(created.type, "notification.created");
    const unread = realtimeEventSchema.parse({
      type: "unread_count.changed",
      payload: { total: 4, by_category: { messages: 4 } },
    });
    assert.equal(unread.type, "unread_count.changed");
  });

  it("rejects malformed notification payloads", () => {
    assert.throws(() =>
      notificationItemSchema.parse({
        notification_id: "not-a-uuid",
        notification_type: "message.received",
        category: "messages",
        title: "x",
        body: "y",
        occurrence_count: 1,
        priority: "normal",
        read: false,
        latest_event_at: "2026-07-29T20:00:00Z",
        created_at: "2026-07-29T19:00:00Z",
      }),
    );
  });

  it("rejects payloads with unexpected sensitive fields via strict schemas", () => {
    assert.throws(() =>
      notificationItemSchema.parse({
        ...sampleItem(),
        push_token: "ExponentPushToken[secret]",
      }),
    );
    assert.throws(() =>
      pushTokenRegisterResponseSchema.parse({
        registered: true,
        provider: "expo",
        device_id: nid,
        token_hash: "abc",
      }),
    );
    for (const field of FORBIDDEN_NOTIFICATION_FIELDS) {
      assert.ok(typeof field === "string");
    }
  });

  it("parses read / read-all / dismiss responses", () => {
    assert.equal(
      readNotificationSchema.parse({
        notification_id: nid,
        read: true,
        read_at: "2026-07-29T21:00:00Z",
      }).read,
      true,
    );
    assert.equal(
      readAllNotificationsSchema.parse({ changed_count: 2 }).changed_count,
      2,
    );
    assert.equal(
      dismissNotificationSchema.parse({
        notification_id: nid,
        dismissed: true,
        dismissed_at: "2026-07-29T21:00:00Z",
      }).dismissed,
      true,
    );
  });
});

describe("Notification helpers", () => {
  it("formats unread badges", () => {
    assert.equal(formatUnreadBadge(0), null);
    assert.equal(formatUnreadBadge(1), "1");
    assert.equal(formatUnreadBadge(99), "99");
    assert.equal(formatUnreadBadge(100), "99+");
    assert.equal(unreadBadgeAccessibilityLabel(0), "No unread notifications");
    assert.equal(unreadBadgeAccessibilityLabel(100), "More than 99 unread notifications");
  });

  it("merges pages without duplicates and upserts updates", () => {
    const a = sampleItem();
    const b = sampleItem({
      notification_id: "33333333-3333-4333-8333-333333333333",
      title: "Other",
    });
    const merged = mergeNotificationPages([{ items: [a, b] }, { items: [a] }]);
    assert.equal(merged.length, 2);
    const updated = upsertNotificationItem(merged, {
      ...a,
      occurrence_count: 3,
      title: "Grouped",
    });
    assert.equal(updated[0]?.occurrence_count ?? updated.find((i) => i.notification_id === nid)?.occurrence_count, 3);
    assert.equal(updated.length, 2);
  });

  it("marks read, dismisses, and clamps unread totals", () => {
    const items = [sampleItem(), sampleItem({ notification_id: "33333333-3333-4333-8333-333333333333" })];
    const read = markNotificationReadInList(items, nid);
    assert.equal(read[0]?.read, true);
    const all = markAllNotificationsRead(items);
    assert.ok(all.every((i) => i.read));
    assert.equal(removeNotificationItem(items, nid).length, 1);
    assert.equal(clampUnreadTotal(-2), 0);
  });

  it("renders actor and accessibility labels safely", () => {
    const item = sampleItem({ occurrence_count: 4, actor: null });
    assert.equal(actorDisplayLabel(item), "Someone");
    assert.match(notificationRowAccessibilityLabel(item), /Unread/);
    assert.match(notificationRowAccessibilityLabel(item), /4 grouped/);
    assert.equal(isMandatoryInAppCategory("account"), true);
    assert.equal(isMandatoryInAppCategory("messages"), false);
    assert.equal(relativeTimestamp("2026-07-29T20:00:00Z", Date.parse("2026-07-29T20:05:00Z")), "5m");
  });

  it("unknown notification types still parse as items", () => {
    const item = sampleItem({ notification_type: "future.unknown_type", category: "weird" });
    assert.equal(item.notification_type, "future.unknown_type");
    assert.match(notificationRowAccessibilityLabel(item), /future|New message|Unread/i);
  });
});
