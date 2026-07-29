import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  containsForbiddenMessagesCopy,
  conversationAccessibilityLabel,
  conversationDisplayName,
  conversationPreview,
  friendlyMessageDeliveryLabel,
} from "./messagesPresentation.ts";

const here = path.dirname(fileURLToPath(import.meta.url));

const sampleConversation = {
  id: "c1",
  other_participant: {
    user_id: "u2",
    handle: "beta",
    display_name: "Dev Beta",
  },
  last_message_preview: "See you on the floor",
  last_message_at: "2026-07-25T12:00:00Z",
  unread_count: 2,
  messaging_allowed: true,
};

describe("Conversation list presentation", () => {
  it("renders real conversation participant and preview", () => {
    assert.equal(conversationDisplayName(sampleConversation), "Dev Beta");
    assert.equal(conversationPreview(sampleConversation), "See you on the floor");
    assert.match(conversationAccessibilityLabel(sampleConversation), /2 unread/);
  });

  it("handles missing preview and messaging disabled gracefully", () => {
    assert.equal(
      conversationPreview({
        ...sampleConversation,
        last_message_preview: null,
        messaging_allowed: false,
      }),
      "Messaging unavailable",
    );
  });
});

describe("Message delivery labels", () => {
  it("uses friendly offline / retry copy", () => {
    assert.equal(friendlyMessageDeliveryLabel("queued"), "Waiting for connection");
    assert.equal(friendlyMessageDeliveryLabel("sending"), "Sending…");
    assert.equal(
      friendlyMessageDeliveryLabel("failed_retryable"),
      "Couldn’t send · Tap to retry",
    );
    assert.equal(friendlyMessageDeliveryLabel("server_confirmed"), "Sent");
  });
});

describe("Messages UI wiring", () => {
  it("conversation list opens the real thread route and shows unread", () => {
    const list = readFileSync(path.join(here, "ConversationsScreen.tsx"), "utf8");
    assert.match(list, /router\.push\(`\/messages\/\$\{item\.id\}`\)/);
    assert.match(list, /conversation-unread-/);
    assert.match(list, /fetchConversations/);
    assert.doesNotMatch(list, /Failed · retry|websocket/i);
    assert.equal(containsForbiddenMessagesCopy("Couldn’t send · Tap to retry"), false);
  });

  it("thread preserves offline queue, optimistic send, and keyboard avoidance", () => {
    const thread = readFileSync(path.join(here, "ConversationScreen.tsx"), "utf8");
    assert.match(thread, /enqueueSendMessage/);
    assert.match(thread, /flushOfflineQueue/);
    assert.match(thread, /KeyboardAvoidingView/);
    assert.match(thread, /friendlyMessageDeliveryLabel/);
    assert.match(thread, /MessagingDisabledState|ConnectionExpiredState/);
    assert.match(thread, /markConversationRead/);
    assert.match(thread, /inverted/);
    assert.doesNotMatch(thread, /Failed · retry/);
    assert.doesNotMatch(thread, /#2563eb|#1e3a5f/);
  });
});
