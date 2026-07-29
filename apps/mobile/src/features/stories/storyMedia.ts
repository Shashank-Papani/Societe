/**
 * Story media selection — reuses FileSystem size reads and ImagePicker.
 * Supports image + short video without changing Live Vibe image-only validation.
 */

import * as ImagePicker from "expo-image-picker";

import {
  ALLOWED_IMAGE_MIME,
  MAX_IMAGE_BYTES,
  MAX_IMAGE_EDGE,
  readFileSize,
  resolveImageMimeType,
  validateSelectedImage,
} from "@/features/experience/uploadHelpers";

export const MAX_STORY_VIDEO_BYTES = 40_000_000;
export const MAX_STORY_VIDEO_DURATION_MS = 15_000;
export const ALLOWED_VIDEO_MIME = new Set(["video/mp4", "video/quicktime"]);

export type StorySelectedMedia = {
  uri: string;
  mimeType: string;
  byteSize: number;
  width: number | null;
  height: number | null;
  mediaType: "image" | "video";
  durationMs: number | null;
};

export type StoryPickResult =
  | { status: "selected"; asset: StorySelectedMedia }
  | { status: "cancelled" }
  | { status: "permission_denied" }
  | { status: "invalid"; message: string };

function resolveVideoMimeType(params: {
  mimeType?: string | null;
  fileName?: string | null;
  uri: string;
}): string | null {
  const declared = params.mimeType?.toLowerCase().trim();
  if (declared && ALLOWED_VIDEO_MIME.has(declared)) {
    return declared;
  }
  const name = (params.fileName ?? params.uri).toLowerCase();
  if (name.endsWith(".mp4")) {
    return "video/mp4";
  }
  if (name.endsWith(".mov") || name.endsWith(".qt")) {
    return "video/quicktime";
  }
  return declared && declared.startsWith("video/") ? declared : null;
}

export async function pickStoryMediaFromLibrary(): Promise<StoryPickResult> {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!permission.granted) {
    return { status: "permission_denied" };
  }

  const picked = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images", "videos"],
    quality: 1,
    exif: false,
    allowsMultipleSelection: false,
    videoMaxDuration: Math.floor(MAX_STORY_VIDEO_DURATION_MS / 1000),
  });

  if (picked.canceled || !picked.assets[0]) {
    return { status: "cancelled" };
  }

  const asset = picked.assets[0];
  const looksVideo =
    asset.type === "video" ||
    (asset.mimeType ?? "").startsWith("video/") ||
    /\.(mp4|mov|qt)$/i.test(asset.fileName ?? asset.uri);

  if (looksVideo) {
    const mimeType = resolveVideoMimeType({
      mimeType: asset.mimeType,
      fileName: asset.fileName,
      uri: asset.uri,
    });
    if (!mimeType || !ALLOWED_VIDEO_MIME.has(mimeType)) {
      return {
        status: "invalid",
        message: "Only MP4 or QuickTime videos are supported for Stories.",
      };
    }
    let byteSize =
      typeof asset.fileSize === "number" && asset.fileSize > 0 ? asset.fileSize : null;
    if (byteSize == null) {
      byteSize = await readFileSize(asset.uri);
    }
    if (byteSize == null || byteSize <= 0) {
      return { status: "invalid", message: "Could not determine the file size." };
    }
    if (byteSize > MAX_STORY_VIDEO_BYTES) {
      return {
        status: "invalid",
        message: `Video exceeds the ${Math.floor(MAX_STORY_VIDEO_BYTES / 1_000_000)} MB limit.`,
      };
    }
    const durationMs =
      typeof asset.duration === "number" && asset.duration > 0
        ? Math.round(asset.duration * 1000)
        : null;
    if (durationMs != null && durationMs > MAX_STORY_VIDEO_DURATION_MS) {
      return {
        status: "invalid",
        message: "Stories videos must be 15 seconds or shorter.",
      };
    }
    return {
      status: "selected",
      asset: {
        uri: asset.uri,
        mimeType,
        byteSize,
        width: asset.width ?? null,
        height: asset.height ?? null,
        mediaType: "video",
        durationMs,
      },
    };
  }

  const mimeType = resolveImageMimeType({
    mimeType: asset.mimeType,
    fileName: asset.fileName,
    uri: asset.uri,
  });
  let byteSize =
    typeof asset.fileSize === "number" && asset.fileSize > 0 ? asset.fileSize : null;
  if (byteSize == null) {
    byteSize = await readFileSize(asset.uri);
  }
  const validated = validateSelectedImage({
    uri: asset.uri,
    mimeType,
    byteSize,
    width: asset.width,
    height: asset.height,
  });
  if (!validated.ok) {
    return { status: "invalid", message: validated.message };
  }
  return {
    status: "selected",
    asset: {
      ...validated.asset,
      durationMs: null,
    },
  };
}

export { ALLOWED_IMAGE_MIME, MAX_IMAGE_BYTES, MAX_IMAGE_EDGE };
