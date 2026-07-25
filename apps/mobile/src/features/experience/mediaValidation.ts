/** Pure client-side media validation (no Expo / RN imports). */

export const MAX_IMAGE_BYTES = 12_000_000;
export const MAX_IMAGE_EDGE = 8192;
export const ALLOWED_IMAGE_MIME = new Set(["image/jpeg", "image/png", "image/webp"]);

export type SelectedMediaAsset = {
  uri: string;
  mimeType: string;
  byteSize: number;
  width: number | null;
  height: number | null;
  mediaType: "image";
};

export type UploadPhase =
  | "idle"
  | "picking"
  | "permission_denied"
  | "cancelled"
  | "validating"
  | "creating_intent"
  | "uploading"
  | "completing"
  | "processing"
  | "published"
  | "rejected"
  | "failed_retryable"
  | "failed_permanent";

export function resolveImageMimeType(params: {
  mimeType?: string | null;
  fileName?: string | null;
  uri: string;
}): string | null {
  const declared = params.mimeType?.toLowerCase().trim();
  if (declared && ALLOWED_IMAGE_MIME.has(declared)) {
    return declared;
  }
  const name = (params.fileName ?? params.uri).toLowerCase();
  if (name.endsWith(".jpg") || name.endsWith(".jpeg")) {
    return "image/jpeg";
  }
  if (name.endsWith(".png")) {
    return "image/png";
  }
  if (name.endsWith(".webp")) {
    return "image/webp";
  }
  return declared && declared.startsWith("image/") ? declared : null;
}

export function validateSelectedImage(params: {
  uri: string;
  mimeType: string | null;
  byteSize: number | null;
  width?: number | null;
  height?: number | null;
}): { ok: true; asset: SelectedMediaAsset } | { ok: false; message: string } {
  if (!params.uri) {
    return { ok: false, message: "Selected media has no file URI." };
  }
  if (!params.mimeType || !ALLOWED_IMAGE_MIME.has(params.mimeType)) {
    return {
      ok: false,
      message: "Only JPEG, PNG, or WebP images are supported in Phase 3.",
    };
  }
  if (params.byteSize == null || params.byteSize <= 0) {
    return { ok: false, message: "Could not determine the file size." };
  }
  if (params.byteSize > MAX_IMAGE_BYTES) {
    return {
      ok: false,
      message: `Image exceeds the ${Math.floor(MAX_IMAGE_BYTES / 1_000_000)} MB limit.`,
    };
  }
  const width = params.width ?? null;
  const height = params.height ?? null;
  if (width != null && height != null) {
    if (width > MAX_IMAGE_EDGE || height > MAX_IMAGE_EDGE) {
      return {
        ok: false,
        message: `Image dimensions exceed ${MAX_IMAGE_EDGE}px on an edge.`,
      };
    }
  }
  return {
    ok: true,
    asset: {
      uri: params.uri,
      mimeType: params.mimeType,
      byteSize: params.byteSize,
      width,
      height,
      mediaType: "image",
    },
  };
}

export function mapLifecycleToPhase(
  lifecycle: string,
  publication: string | null | undefined,
): UploadPhase {
  if (publication === "published" || lifecycle === "ready") {
    return "published";
  }
  if (
    lifecycle === "rejected" ||
    lifecycle === "invalid" ||
    lifecycle === "revoked" ||
    lifecycle === "deleted"
  ) {
    return "rejected";
  }
  if (lifecycle === "processing_failed" || lifecycle === "upload_expired") {
    return "failed_retryable";
  }
  if (
    lifecycle === "uploaded" ||
    lifecycle === "validating" ||
    lifecycle === "processing" ||
    lifecycle === "moderation_pending" ||
    lifecycle === "manual_review"
  ) {
    return "processing";
  }
  return "processing";
}
