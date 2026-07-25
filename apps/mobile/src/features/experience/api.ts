import { z } from "zod";

import { apiFetch } from "@/api/client";
import { getStoredDeviceId } from "@/auth/deviceStore";

import * as Crypto from "expo-crypto";

const variantSchema = z.object({
  variant_type: z.string(),
  mime_type: z.string(),
  url: z.string(),
  width: z.number().nullable().optional(),
  height: z.number().nullable().optional(),
  duration_ms: z.number().nullable().optional(),
  expires_at: z.string(),
});

const vibeItemSchema = z.object({
  id: z.string(),
  venue_id: z.string(),
  media_type: z.enum(["image", "video"]),
  attribution_mode: z.enum(["attributed", "anonymous"]),
  author: z
    .object({
      id: z.string(),
      handle: z.string(),
      display_name: z.string(),
    })
    .nullable(),
  author_label: z.string(),
  caption: z.string().nullable().optional(),
  vibe_tags: z.array(z.string()),
  published_at: z.string(),
  expires_at: z.string(),
  variants: z.array(variantSchema),
  viewer_is_author: z.boolean(),
});

const feedSchema = z.object({
  items: z.array(vibeItemSchema),
  next_cursor: z.string().nullable(),
});

const uploadCreateSchema = z.object({
  upload_id: z.string(),
  live_vibe_id: z.string(),
  lifecycle_status: z.string(),
  attribution_mode: z.enum(["attributed", "anonymous"]),
  intent_expires_at: z.string(),
  max_byte_size: z.number(),
  upload: z.object({
    method: z.literal("PUT"),
    url: z.string(),
    headers: z.record(z.string(), z.string()),
    expires_at: z.string(),
  }),
});

const uploadStatusSchema = z.object({
  upload_id: z.string(),
  media_type: z.enum(["image", "video"]),
  lifecycle_status: z.string(),
  moderation_status: z.string(),
  attribution_mode: z.enum(["attributed", "anonymous"]),
  live_vibe_id: z.string().nullable().optional(),
  publication_status: z.string().nullable().optional(),
  published_at: z.string().nullable().optional(),
  expires_at: z.string().nullable().optional(),
  intent_expires_at: z.string().nullable().optional(),
  variants: z.array(variantSchema),
  failure_reason: z.string().nullable().optional(),
});

export type VibeFeedItem = z.infer<typeof vibeItemSchema>;
export type UploadStatus = z.infer<typeof uploadStatusSchema>;

export async function fetchVenueVibes(venueId: string, cursor?: string | null) {
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) {
    query.set("cursor", cursor);
  }
  const envelope = await apiFetch<z.infer<typeof feedSchema>>(
    `/v1/venues/${venueId}/vibes?${query}`,
  );
  return feedSchema.parse(envelope.data);
}

export async function createMediaUpload(input: {
  venueId: string;
  mediaType: "image" | "video";
  mimeType: string;
  byteSize: number;
  caption?: string;
  vibeTags?: string[];
}) {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) {
    throw new Error("Register a device first (sign in on Profile).");
  }
  const idempotencyKey = Crypto.randomUUID();
  const envelope = await apiFetch<z.infer<typeof uploadCreateSchema>>("/v1/media/uploads", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      venue_id: input.venueId,
      device_id: deviceId,
      media_type: input.mediaType,
      mime_type: input.mimeType,
      byte_size: input.byteSize,
      caption: input.caption ?? null,
      vibe_tags: input.vibeTags ?? [],
    }),
  });
  return uploadCreateSchema.parse(envelope.data);
}

export async function completeMediaUpload(uploadId: string) {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) {
    throw new Error("Register a device first (sign in on Profile).");
  }
  const idempotencyKey = `complete-${uploadId}`;
  const envelope = await apiFetch<z.infer<typeof uploadStatusSchema>>(
    `/v1/media/uploads/${uploadId}/complete`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ device_id: deviceId }),
    },
  );
  return uploadStatusSchema.parse(envelope.data);
}

export async function fetchUploadStatus(uploadId: string) {
  const envelope = await apiFetch<z.infer<typeof uploadStatusSchema>>(
    `/v1/media/uploads/${uploadId}`,
  );
  return uploadStatusSchema.parse(envelope.data);
}

export async function reportVibe(vibeId: string, reason: string) {
  const envelope = await apiFetch<{ report_id: string }>(`/v1/vibes/${vibeId}/reports`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
  return envelope.data;
}
