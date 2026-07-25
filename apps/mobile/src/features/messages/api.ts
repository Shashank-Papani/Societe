import * as Crypto from "expo-crypto";
import { z } from "zod";

import { apiFetch } from "@/api/client";

const participantSchema = z.object({
  user_id: z.string(),
  handle: z.string().nullable().optional(),
  display_name: z.string().nullable().optional(),
});

const conversationSummarySchema = z.object({
  id: z.string(),
  other_participant: participantSchema,
  last_message_preview: z.string().nullable().optional(),
  last_message_at: z.string().nullable().optional(),
  unread_count: z.number(),
  archived_at: z.string().nullable().optional(),
  messaging_allowed: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});

const conversationListSchema = z.object({
  items: z.array(conversationSummarySchema),
  next_cursor: z.string().nullable().optional(),
});

const conversationDetailSchema = conversationSummarySchema.extend({
  originating_connection_grant_id: z.string(),
});

const messageSchema = z.object({
  id: z.string(),
  conversation_id: z.string(),
  sender_user_id: z.string(),
  client_message_id: z.string(),
  body: z.string().nullable(),
  status: z.enum(["sent", "deleted"]),
  created_at: z.string(),
  edited_at: z.string().nullable().optional(),
  deleted_at: z.string().nullable().optional(),
});

const messageListSchema = z.object({
  items: z.array(messageSchema),
  next_cursor: z.string().nullable().optional(),
});

const markReadSchema = z.object({
  conversation_id: z.string(),
  last_read_message_id: z.string().nullable().optional(),
  last_read_at: z.string().nullable().optional(),
  unread_count: z.number(),
});

export type ConversationSummary = z.infer<typeof conversationSummarySchema>;
export type MessageSummary = z.infer<typeof messageSchema>;

export function newClientMessageId(): string {
  return Crypto.randomUUID();
}

export async function fetchConversations(options?: {
  includeArchived?: boolean;
  cursor?: string | null;
}): Promise<z.infer<typeof conversationListSchema>> {
  const params = new URLSearchParams();
  if (options?.includeArchived) {
    params.set("include_archived", "true");
  }
  if (options?.cursor) {
    params.set("cursor", options.cursor);
  }
  const qs = params.toString();
  const envelope = await apiFetch<unknown>(`/v1/conversations${qs ? `?${qs}` : ""}`);
  return conversationListSchema.parse(envelope.data);
}

export async function createConversation(input: {
  otherUserId?: string;
  connectionGrantId?: string;
}): Promise<z.infer<typeof conversationDetailSchema>> {
  const body =
    input.connectionGrantId != null
      ? { connection_grant_id: input.connectionGrantId }
      : { other_user_id: input.otherUserId };
  const envelope = await apiFetch<unknown>("/v1/conversations", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return conversationDetailSchema.parse(envelope.data);
}

export async function fetchMessages(
  conversationId: string,
  cursor?: string | null,
): Promise<z.infer<typeof messageListSchema>> {
  const params = new URLSearchParams();
  if (cursor) {
    params.set("cursor", cursor);
  }
  const qs = params.toString();
  const envelope = await apiFetch<unknown>(
    `/v1/conversations/${conversationId}/messages${qs ? `?${qs}` : ""}`,
  );
  return messageListSchema.parse(envelope.data);
}

export async function sendMessage(
  conversationId: string,
  input: { body: string; clientMessageId: string },
): Promise<MessageSummary> {
  const envelope = await apiFetch<unknown>(`/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: {
      "Idempotency-Key": input.clientMessageId,
    },
    body: JSON.stringify({
      body: input.body,
      client_message_id: input.clientMessageId,
    }),
  });
  return messageSchema.parse(envelope.data);
}

export async function markConversationRead(
  conversationId: string,
  lastReadMessageId?: string | null,
): Promise<z.infer<typeof markReadSchema>> {
  const envelope = await apiFetch<unknown>(`/v1/conversations/${conversationId}/read`, {
    method: "POST",
    body: JSON.stringify({
      last_read_message_id: lastReadMessageId ?? null,
    }),
  });
  return markReadSchema.parse(envelope.data);
}
