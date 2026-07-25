import * as Crypto from "expo-crypto";
import { z } from "zod";

import { apiFetch } from "@/api/client";

const callingCardStatusSchema = z.enum([
  "pending",
  "accepted",
  "declined",
  "expired",
  "cancelled",
  "blocked",
]);

const responseActionSchema = z.enum(["share_info", "make_move", "accept_only"]);
const shareScopeSchema = z.enum([
  "instagram",
  "spotify",
  "phone",
  "snapchat",
  "display_name",
]);

const discoverableUserSchema = z.object({
  user_id: z.string(),
  handle: z.string(),
  display_name: z.string(),
});

const discoverableUsersSchema = z.object({
  venue_id: z.string(),
  items: z.array(discoverableUserSchema),
});

const callingCardSummarySchema = z.object({
  id: z.string(),
  status: callingCardStatusSchema,
  venue_id: z.string(),
  sender_user_id: z.string(),
  recipient_user_id: z.string(),
  reason_code: z.string().nullable().optional(),
  reason_text: z.string().nullable().optional(),
  created_at: z.string(),
  expires_at: z.string(),
  responded_at: z.string().nullable().optional(),
  response_action: responseActionSchema.nullable().optional(),
});

const callingCardCreateSchema = z.object({
  id: z.string(),
  status: callingCardStatusSchema,
  venue_id: z.string(),
  expires_at: z.string(),
});

const callingCardListSchema = z.object({
  items: z.array(callingCardSummarySchema),
});

const connectionGrantSchema = z.object({
  id: z.string(),
  calling_card_id: z.string(),
  scopes: z.array(z.string()),
  expires_at: z.string(),
  revoked_at: z.string().nullable().optional(),
});

const callingCardDetailSchema = z.object({
  card: callingCardSummarySchema,
  grant: connectionGrantSchema.nullable(),
});

const callingCardStatusResponseSchema = z.object({
  id: z.string(),
  status: callingCardStatusSchema,
  expires_at: z.string(),
  responded_at: z.string().nullable().optional(),
});

const respondResponseSchema = z.object({
  card: callingCardSummarySchema,
  grant: connectionGrantSchema.nullable(),
});

const blockResponseSchema = z.object({
  blocker_user_id: z.string(),
  blocked_user_id: z.string(),
  created_at: z.string(),
});

const unblockResponseSchema = z.object({
  blocker_user_id: z.string(),
  blocked_user_id: z.string(),
  removed: z.boolean(),
});

export type DiscoverableUser = z.infer<typeof discoverableUserSchema>;
export type CallingCardSummary = z.infer<typeof callingCardSummarySchema>;
export type CallingCardCreateResult = z.infer<typeof callingCardCreateSchema>;
export type CallingCardStatus = z.infer<typeof callingCardStatusSchema>;
export type ShareScope = z.infer<typeof shareScopeSchema>;
export type ResponseDecision = "accept" | "decline";

export const CALLING_CARD_REASON_CODES = [
  "love_the_dance_moves",
  "great_conversation",
  "nice_style",
  "shared_vibe",
  "say_hello",
] as const;

export type CallingCardReasonCode = (typeof CALLING_CARD_REASON_CODES)[number];

export function newIdempotencyKey(): string {
  return Crypto.randomUUID();
}

export async function fetchDiscoverableUsers() {
  const envelope = await apiFetch<z.infer<typeof discoverableUsersSchema>>(
    "/v1/venues/me/discoverable-users",
  );
  return discoverableUsersSchema.parse(envelope.data);
}

export async function createCallingCard(
  input: {
    recipientUserId: string;
    reasonCode?: string | null;
    reasonText?: string | null;
  },
  idempotencyKey: string = newIdempotencyKey(),
) {
  const envelope = await apiFetch<z.infer<typeof callingCardCreateSchema>>(
    "/v1/calling-cards",
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        recipient_user_id: input.recipientUserId,
        reason_code: input.reasonCode ?? null,
        reason_text: input.reasonText ?? null,
      }),
    },
  );
  return callingCardCreateSchema.parse(envelope.data);
}

export async function fetchCallingCardInbox() {
  const envelope = await apiFetch<z.infer<typeof callingCardListSchema>>(
    "/v1/calling-cards/inbox",
  );
  return callingCardListSchema.parse(envelope.data);
}

export async function fetchCallingCardSent() {
  const envelope = await apiFetch<z.infer<typeof callingCardListSchema>>(
    "/v1/calling-cards/sent",
  );
  return callingCardListSchema.parse(envelope.data);
}

export async function fetchCallingCardDetail(callingCardId: string) {
  const envelope = await apiFetch<z.infer<typeof callingCardDetailSchema>>(
    `/v1/calling-cards/${callingCardId}`,
  );
  return callingCardDetailSchema.parse(envelope.data);
}

export async function fetchCallingCardStatus(callingCardId: string) {
  const envelope = await apiFetch<z.infer<typeof callingCardStatusResponseSchema>>(
    `/v1/calling-cards/${callingCardId}/status`,
  );
  return callingCardStatusResponseSchema.parse(envelope.data);
}

export async function respondCallingCard(
  callingCardId: string,
  input: {
    decision: ResponseDecision;
    action?: "share_info" | "make_move" | "accept_only" | null;
    shareScopes?: ShareScope[];
  },
  idempotencyKey: string = newIdempotencyKey(),
) {
  const envelope = await apiFetch<z.infer<typeof respondResponseSchema>>(
    `/v1/calling-cards/${callingCardId}/respond`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        decision: input.decision,
        action: input.action ?? null,
        share_scopes: input.shareScopes ?? [],
      }),
    },
  );
  return respondResponseSchema.parse(envelope.data);
}

export async function cancelCallingCard(
  callingCardId: string,
  idempotencyKey: string = newIdempotencyKey(),
) {
  const envelope = await apiFetch<z.infer<typeof callingCardSummarySchema>>(
    `/v1/calling-cards/${callingCardId}/cancel`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    },
  );
  return callingCardSummarySchema.parse(envelope.data);
}

export async function shareCallingCard(
  callingCardId: string,
  shareScopes: ShareScope[],
) {
  const scopes = z.array(shareScopeSchema).parse(shareScopes);
  const envelope = await apiFetch<z.infer<typeof callingCardDetailSchema>>(
    `/v1/calling-cards/${callingCardId}/share`,
    {
      method: "POST",
      body: JSON.stringify({ share_scopes: scopes }),
    },
  );
  return callingCardDetailSchema.parse(envelope.data);
}

export async function blockUser(userId: string, reasonCode?: string | null) {
  const envelope = await apiFetch<z.infer<typeof blockResponseSchema>>(
    `/v1/users/${userId}/block`,
    {
      method: "POST",
      body: JSON.stringify({ reason_code: reasonCode ?? null }),
    },
  );
  return blockResponseSchema.parse(envelope.data);
}

export async function unblockUser(userId: string) {
  const envelope = await apiFetch<z.infer<typeof unblockResponseSchema>>(
    `/v1/users/${userId}/block`,
    { method: "DELETE" },
  );
  return unblockResponseSchema.parse(envelope.data);
}
