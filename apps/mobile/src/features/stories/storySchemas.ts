/**
 * Pure Stories + official-post Zod contracts (no Expo / RN imports).
 * Schema failures are logged only in __DEV__ and never include tokens or signed URLs.
 */

import { z } from "zod";

function logSchemaError(context: string, error: unknown): void {
  if (typeof __DEV__ !== "undefined" && !__DEV__) {
    return;
  }
  // In Node tests __DEV__ may be undefined — still avoid logging bodies.
  if (typeof __DEV__ === "undefined") {
    // no-op outside RN, but keep signature for shared parseStrict
  }
  const message = error instanceof Error ? error.message : "schema_error";
  // Never log response bodies — they may contain signed URLs.
  if (typeof console !== "undefined" && typeof __DEV__ !== "undefined" && __DEV__) {
    console.warn(`[stories] ${context}: ${message}`);
  }
}

export function parseStoryPayload<T>(schema: z.ZodType<T>, data: unknown, context: string): T {
  try {
    return schema.parse(data);
  } catch (error) {
    logSchemaError(context, error);
    throw error;
  }
}

export const mediaVariantSchema = z.object({
  variant_type: z.string(),
  mime_type: z.string(),
  url: z.string(),
  width: z.number().nullable().optional(),
  height: z.number().nullable().optional(),
  duration_ms: z.number().nullable().optional(),
  expires_at: z.string(),
});

export const storyAuthorProjectionSchema = z
  .object({
    id: z.string().uuid().nullable().optional(),
    handle: z.string().nullable().optional(),
    display_name: z.string().nullable().optional(),
  })
  .strict();

export const venueStoryProjectionSchema = z
  .object({
    id: z.string().uuid(),
    name: z.string(),
    slug: z.string().nullable().optional(),
  })
  .strict();

export const storyGroupSummarySchema = z
  .object({
    group_key: z.string().min(1),
    group_type: z.enum(["venue", "user", "anon"]),
    venue_id: z.string().uuid().nullable().optional(),
    author: storyAuthorProjectionSchema.nullable().optional(),
    author_label: z.string(),
    venue: venueStoryProjectionSchema.nullable().optional(),
    is_official: z.boolean().optional().default(false),
    is_mine: z.boolean().optional().default(false),
    preview_variants: z.array(mediaVariantSchema).optional().default([]),
    active_count: z.number().int().nonnegative(),
    unviewed_count: z.number().int().nonnegative(),
    latest_published_at: z.string(),
    earliest_expires_at: z.string(),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.group_type === "anon" && value.author != null) {
      ctx.addIssue({
        code: "custom",
        message: "Anonymous Story groups must not include an author projection.",
        path: ["author"],
      });
    }
    if (value.is_official && value.author != null) {
      ctx.addIssue({
        code: "custom",
        message: "Official Story groups must not include a staff author projection.",
        path: ["author"],
      });
    }
  });

export const storySlideSchema = z
  .object({
    story_id: z.string().uuid(),
    venue_id: z.string().uuid(),
    media_type: z.enum(["image", "video"]),
    attribution_mode: z.enum(["attributed", "anonymous", "official"]),
    author: storyAuthorProjectionSchema.nullable().optional(),
    author_label: z.string(),
    venue: venueStoryProjectionSchema.nullable().optional(),
    is_official: z.boolean().optional().default(false),
    caption: z.string().nullable().optional(),
    vibe_tags: z.array(z.string()).optional().default([]),
    reply_policy: z.enum(["disabled", "connections", "everyone"]),
    published_at: z.string(),
    expires_at: z.string(),
    viewed: z.boolean().optional().default(false),
    is_mine: z.boolean().optional().default(false),
    can_report: z.boolean().optional().default(false),
    can_delete: z.boolean().optional().default(false),
    variants: z.array(mediaVariantSchema).optional().default([]),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.attribution_mode === "anonymous" && value.author != null) {
      ctx.addIssue({
        code: "custom",
        message: "Anonymous slides must not include an author projection.",
        path: ["author"],
      });
    }
    if (
      (value.attribution_mode === "official" || value.is_official) &&
      value.author != null
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Official slides must not include a staff author projection.",
        path: ["author"],
      });
    }
  });

export const storyGroupDetailSchema = z
  .object({
    group_key: z.string().min(1),
    group_type: z.enum(["venue", "user", "anon"]),
    venue_id: z.string().uuid().nullable().optional(),
    author_label: z.string(),
    is_official: z.boolean().optional().default(false),
    is_mine: z.boolean().optional().default(false),
    slides: z.array(storySlideSchema),
  })
  .strict();

export const storyGroupListSchema = z
  .object({
    items: z.array(storyGroupSummarySchema),
  })
  .strict();

const uploadInstructionSchema = z
  .object({
    method: z.literal("PUT"),
    url: z.string(),
    headers: z.record(z.string(), z.string()),
    expires_at: z.string(),
  })
  .strict();

export const storyUploadResponseSchema = z
  .object({
    story_id: z.string().uuid(),
    upload_id: z.string().uuid(),
    media_asset_id: z.string().uuid(),
    lifecycle_status: z.string(),
    publication_status: z.string(),
    moderation_status: z.string(),
    attribution_mode: z.enum(["attributed", "anonymous", "official"]),
    intent_expires_at: z.string(),
    max_byte_size: z.number().int().positive(),
    upload: uploadInstructionSchema.nullable().optional(),
    variants: z.array(mediaVariantSchema).optional().default([]),
    failure_reason: z.string().nullable().optional(),
    expires_at: z.string().nullable().optional(),
    published_at: z.string().nullable().optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    const blob = JSON.stringify(value);
    if (blob.includes("object_key") || blob.includes("quarantine_object_key")) {
      ctx.addIssue({
        code: "custom",
        message: "Story upload responses must not expose storage object keys.",
      });
    }
  });

export const recordStoryViewResponseSchema = z
  .object({
    story_id: z.string().uuid(),
    viewed: z.boolean().optional().default(true),
    viewed_at: z.string(),
  })
  .strict();

export const STORY_REPORT_REASONS = [
  "spam",
  "harassment",
  "sexual_content",
  "violence",
  "hate",
  "illegal",
  "other",
] as const;

export type StoryReportReason = (typeof STORY_REPORT_REASONS)[number];

export const createStoryReportRequestSchema = z
  .object({
    reason: z.enum(STORY_REPORT_REASONS),
    description: z.string().nullable().optional(),
  })
  .strict();

export const createStoryReportResponseSchema = z
  .object({
    report_id: z.string().uuid(),
    story_id: z.string().uuid(),
    reason: z.enum(STORY_REPORT_REASONS),
    status: z.enum(["open", "reviewing", "resolved", "dismissed"]),
    created_at: z.string(),
  })
  .strict();

export const deleteStoryResponseSchema = z
  .object({
    story_id: z.string().uuid(),
    publication_status: z.string(),
  })
  .strict();

export const officialPostSummarySchema = z
  .object({
    post_id: z.string().uuid(),
    venue_id: z.string().uuid(),
    post_type: z.enum([
      "announcement",
      "event",
      "dj",
      "special",
      "policy",
      "promotion",
      "general",
    ]),
    title: z.string().nullable().optional(),
    body: z.string(),
    call_to_action_type: z.string().nullable().optional(),
    call_to_action_url: z.string().nullable().optional(),
    publication_status: z.string(),
    published_at: z.string().nullable().optional(),
    is_official: z.boolean().optional().default(true),
    author_label: z.string(),
    venue: venueStoryProjectionSchema.nullable().optional(),
    variants: z.array(mediaVariantSchema).optional().default([]),
  })
  .strict()
  .superRefine((value, ctx) => {
    const keys = Object.keys(value);
    if (keys.includes("created_by_user_id") || keys.includes("attribution_mode")) {
      ctx.addIssue({
        code: "custom",
        message: "Official posts must not expose staff identity fields.",
      });
    }
  });

export const officialPostDetailSchema = officialPostSummarySchema.extend({
  created_at: z.string(),
});

export const officialPostListSchema = z
  .object({
    items: z.array(officialPostSummarySchema),
    next_cursor: z.string().nullable().optional(),
  })
  .strict();

export type MediaVariant = z.infer<typeof mediaVariantSchema>;
export type StoryGroupSummary = z.infer<typeof storyGroupSummarySchema>;
export type StorySlide = z.infer<typeof storySlideSchema>;
export type StoryGroupDetail = z.infer<typeof storyGroupDetailSchema>;
export type StoryUploadResponse = z.infer<typeof storyUploadResponseSchema>;
export type OfficialPostSummary = z.infer<typeof officialPostSummarySchema>;
export type OfficialPostDetail = z.infer<typeof officialPostDetailSchema>;

