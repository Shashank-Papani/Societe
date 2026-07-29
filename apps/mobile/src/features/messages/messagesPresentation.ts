/**
 * Messages list / thread presentation helpers.
 */

export type ConversationLike = {
  id: string;
  other_participant: {
    user_id: string;
    handle?: string | null;
    display_name?: string | null;
  };
  last_message_preview?: string | null;
  last_message_at?: string | null;
  unread_count: number;
  messaging_allowed: boolean;
};

export function conversationDisplayName(item: ConversationLike): string {
  return (
    item.other_participant.display_name?.trim() ||
    (item.other_participant.handle ? `@${item.other_participant.handle}` : "Connection")
  );
}

export function conversationPreview(item: ConversationLike): string {
  const preview = item.last_message_preview?.trim();
  if (preview) {
    return preview;
  }
  if (!item.messaging_allowed) {
    return "Messaging unavailable";
  }
  return "No messages yet";
}

export function conversationAccessibilityLabel(item: ConversationLike): string {
  const name = conversationDisplayName(item);
  const unread = item.unread_count > 0 ? `, ${item.unread_count} unread` : "";
  return `${name}${unread}`;
}

export function formatMessageClock(iso: string | null | undefined): string {
  if (!iso) {
    return "";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  } catch {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
}

export function formatConversationTimestamp(
  iso: string | null | undefined,
  nowMs: number = Date.now(),
): string | null {
  if (!iso) {
    return null;
  }
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) {
    return null;
  }
  const delta = Math.max(0, nowMs - then);
  const minutes = Math.floor(delta / 60_000);
  if (minutes < 1) {
    return "Now";
  }
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
  try {
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(
      new Date(then),
    );
  } catch {
    return new Date(then).toLocaleDateString();
  }
}

export function friendlyMessageDeliveryLabel(queueState: string): string {
  switch (queueState) {
    case "queued":
      return "Waiting for connection";
    case "sending":
      return "Sending…";
    case "failed_retryable":
    case "failed_permanent":
      return "Couldn’t send · Tap to retry";
    case "server_confirmed":
    case "acknowledged":
      return "Sent";
    default:
      return "Sent";
  }
}

export function containsForbiddenMessagesCopy(text: string): boolean {
  return /(calling_card\.|message\.send|Failed · retry|websocket|queue op|NETWORK)/i.test(
    text,
  );
}
