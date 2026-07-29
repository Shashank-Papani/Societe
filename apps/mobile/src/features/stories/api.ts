/**
 * Stories + official-post API client (snake_case Zod matching OpenAPI).
 */

import * as Crypto from "expo-crypto";

import { apiFetch } from "@/api/client";
import { getStoredDeviceId } from "@/auth/deviceStore";
import {
  createStoryReportResponseSchema,
  deleteStoryResponseSchema,
  officialPostDetailSchema,
  officialPostListSchema,
  parseStoryPayload,
  recordStoryViewResponseSchema,
  storyGroupDetailSchema,
  storyGroupListSchema,
  storyUploadResponseSchema,
  type StoryReportReason,
} from "@/features/stories/storySchemas";

export * from "@/features/stories/storySchemas";

export async function fetchExperienceStoryGroups() {
  const envelope = await apiFetch<unknown>("/v1/experience/stories");
  return parseStoryPayload(storyGroupListSchema, envelope.data, "experience_stories");
}

export async function fetchStoryGroup(groupKey: string) {
  const encoded = encodeURIComponent(groupKey);
  const envelope = await apiFetch<unknown>(`/v1/story-groups/${encoded}`);
  return parseStoryPayload(storyGroupDetailSchema, envelope.data, "story_group");
}

export async function createUserStoryUpload(
  input: {
    venueId: string;
    mediaType: "image" | "video";
    mimeType: string;
    byteSize: number;
    caption?: string | null;
    vibeTags?: string[];
    attributionMode: "attributed" | "anonymous";
    replyPolicy?: "disabled" | "connections" | "everyone";
  },
  options?: { idempotencyKey?: string },
) {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) {
    throw new Error("Register a device first (sign in on Profile).");
  }
  const idempotencyKey = options?.idempotencyKey ?? Crypto.randomUUID();
  const envelope = await apiFetch<unknown>("/v1/stories/uploads", {
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
      attribution_mode: input.attributionMode,
      reply_policy: input.replyPolicy ?? "disabled",
    }),
  });
  return {
    response: parseStoryPayload(storyUploadResponseSchema, envelope.data, "story_upload_intent"),
    idempotencyKey,
  };
}

export async function completeUserStoryUpload(uploadId: string) {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) {
    throw new Error("Register a device first (sign in on Profile).");
  }
  const envelope = await apiFetch<unknown>(`/v1/story-uploads/${uploadId}/complete`, {
    method: "POST",
    headers: { "Idempotency-Key": `story-complete-${uploadId}` },
    body: JSON.stringify({ device_id: deviceId }),
  });
  return parseStoryPayload(storyUploadResponseSchema, envelope.data, "story_upload_complete");
}

export async function fetchStoryUploadStatus(uploadId: string) {
  const envelope = await apiFetch<unknown>(`/v1/story-uploads/${uploadId}`);
  return parseStoryPayload(storyUploadResponseSchema, envelope.data, "story_upload_status");
}

export async function recordStoryView(storyId: string) {
  const envelope = await apiFetch<unknown>(`/v1/stories/${storyId}/views`, {
    method: "POST",
  });
  return parseStoryPayload(recordStoryViewResponseSchema, envelope.data, "story_view");
}

export async function reportStory(
  storyId: string,
  input: { reason: StoryReportReason; description?: string | null },
) {
  const envelope = await apiFetch<unknown>(`/v1/stories/${storyId}/reports`, {
    method: "POST",
    headers: { "Idempotency-Key": Crypto.randomUUID() },
    body: JSON.stringify({
      reason: input.reason,
      description: input.description ?? null,
    }),
  });
  return parseStoryPayload(createStoryReportResponseSchema, envelope.data, "story_report");
}

export async function deleteStory(storyId: string) {
  const envelope = await apiFetch<unknown>(`/v1/stories/${storyId}`, {
    method: "DELETE",
  });
  return parseStoryPayload(deleteStoryResponseSchema, envelope.data, "story_delete");
}

export async function fetchVenueOfficialPosts(venueId: string, cursor?: string | null) {
  const query = new URLSearchParams();
  if (cursor) {
    query.set("cursor", cursor);
  }
  const suffix = query.toString() ? `?${query}` : "";
  const envelope = await apiFetch<unknown>(`/v1/venues/${venueId}/official-posts${suffix}`);
  return parseStoryPayload(officialPostListSchema, envelope.data, "official_posts");
}

export async function fetchOfficialPost(postId: string) {
  const envelope = await apiFetch<unknown>(`/v1/official-posts/${postId}`);
  return parseStoryPayload(officialPostDetailSchema, envelope.data, "official_post");
}
