/**
 * Pure notification presentation helpers (no Expo / RN imports).
 */

import type { NotificationItem, NotificationCategory } from "./notificationSchemas";

const KNOWN_CATEGORIES: readonly NotificationCategory[] = [
  "messages",
  "calling_cards",
  "stories",
  "venue_management",
  "account",
];

export function formatUnreadBadge(total: number): string | null {
  if (!Number.isFinite(total) || total <= 0) {
    return null;
  }
  if (total > 99) {
    return "99+";
  }
  return String(Math.floor(total));
}

export function unreadBadgeAccessibilityLabel(total: number): string {
  if (total <= 0) {
    return "No unread notifications";
  }
  if (total === 1) {
    return "1 unread notification";
  }
  if (total > 99) {
    return "More than 99 unread notifications";
  }
  return `${total} unread notifications`;
}

export function categoryLabel(category: string): string {
  switch (category) {
    case "messages":
      return "Messages";
    case "calling_cards":
      return "Calling Cards";
    case "stories":
      return "Stories";
    case "venue_management":
      return "Venue Management";
    case "account":
      return "Account";
    default:
      return "Notifications";
  }
}

export function isKnownCategory(category: string): category is NotificationCategory {
  return (KNOWN_CATEGORIES as readonly string[]).includes(category);
}

export function isMandatoryInAppCategory(category: string): boolean {
  return category === "account";
}

export function actorDisplayLabel(item: NotificationItem): string {
  if (item.actor?.label) {
    return item.actor.label;
  }
  return "Someone";
}

export function notificationRowAccessibilityLabel(item: NotificationItem): string {
  const state = item.read ? "Read" : "Unread";
  const count =
    item.occurrence_count > 1 ? `, ${item.occurrence_count} grouped` : "";
  return `${state} notification: ${item.title}. ${item.body}${count}`;
}

export function relativeTimestamp(iso: string, nowMs: number = Date.now()): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) {
    return "";
  }
  const deltaSec = Math.max(0, Math.floor((nowMs - then) / 1000));
  if (deltaSec < 60) {
    return "Just now";
  }
  const minutes = Math.floor(deltaSec / 60);
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h`;
  }
  const days = Math.floor(hours / 24);
  if (days < 7) {
    return `${days}d`;
  }
  return new Date(then).toLocaleDateString();
}

export function mergeNotificationPages(
  pages: { items: NotificationItem[] }[],
): NotificationItem[] {
  const seen = new Set<string>();
  const out: NotificationItem[] = [];
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.notification_id)) {
        continue;
      }
      seen.add(item.notification_id);
      out.push(item);
    }
  }
  return out;
}

export function upsertNotificationItem(
  items: NotificationItem[],
  next: NotificationItem,
): NotificationItem[] {
  const index = items.findIndex((item) => item.notification_id === next.notification_id);
  if (index < 0) {
    return [next, ...items];
  }
  const copy = items.slice();
  copy[index] = next;
  return copy;
}

export function removeNotificationItem(
  items: NotificationItem[],
  notificationId: string,
): NotificationItem[] {
  return items.filter((item) => item.notification_id !== notificationId);
}

export function markNotificationReadInList(
  items: NotificationItem[],
  notificationId: string,
): NotificationItem[] {
  return items.map((item) =>
    item.notification_id === notificationId ? { ...item, read: true } : item,
  );
}

export function markAllNotificationsRead(items: NotificationItem[]): NotificationItem[] {
  return items.map((item) => (item.read ? item : { ...item, read: true }));
}

export function clampUnreadTotal(total: number): number {
  if (!Number.isFinite(total) || total < 0) {
    return 0;
  }
  return Math.floor(total);
}

/** Bounded exponential backoff with full jitter (ms). */
export function realtimeBackoffMs(attempt: number): number {
  const capped = Math.min(30_000, 1000 * 2 ** Math.max(0, attempt - 1));
  return Math.floor(Math.random() * (capped + 1));
}
