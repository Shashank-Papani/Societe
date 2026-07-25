/**
 * Pure profile-photo UI helpers (no Expo / RN imports).
 * Display never uses quarantine or rejected bytes — only the last approved URL.
 */

export const PROFILE_PHOTO_MAX_BYTES = 5_000_000;
export const PROFILE_PHOTO_ALLOWED_MIME = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

export type ProfilePhotoPhase =
  | "idle"
  | "uploading"
  | "processing"
  | "approved"
  | "rejected"
  | "retry";

export type ProfilePhotoDisplayMode = "placeholder" | "remote" | "approved_marker";

export type ProfilePhotoDisplay = {
  mode: ProfilePhotoDisplayMode;
  /** Remote http(s) URL when mode is remote; otherwise null. */
  uri: string | null;
  hasApprovedPhoto: boolean;
};

export type SelectedProfilePhoto = {
  uri: string;
  mimeType: string;
  byteSize: number;
  width: number | null;
  height: number | null;
};

export function hasApprovedProfilePhoto(url: string | null | undefined): boolean {
  return typeof url === "string" && url.trim().length > 0;
}

export function isDisplayablePhotoUrl(url: string | null | undefined): boolean {
  return typeof url === "string" && /^https?:\/\//i.test(url.trim());
}

/**
 * Visible photo while idle / uploading / processing / rejected.
 * Always prefers the last approved photo; never the in-flight selection.
 */
export function resolveVisibleProfilePhoto(params: {
  approvedUrl: string | null | undefined;
  phase: ProfilePhotoPhase;
}): ProfilePhotoDisplay {
  void params.phase; // phase does not swap display to pending bytes
  const approved = params.approvedUrl?.trim() || null;
  if (isDisplayablePhotoUrl(approved)) {
    return { mode: "remote", uri: approved, hasApprovedPhoto: true };
  }
  if (hasApprovedProfilePhoto(approved)) {
    return { mode: "approved_marker", uri: null, hasApprovedPhoto: true };
  }
  return { mode: "placeholder", uri: null, hasApprovedPhoto: false };
}

export function chooseOrReplaceLabel(hasApprovedPhoto: boolean): "Choose photo" | "Replace photo" {
  return hasApprovedPhoto ? "Replace photo" : "Choose photo";
}

export function profilePhotoStatusLabel(
  phase: ProfilePhotoPhase,
  uploadProgress: number | null,
): string | null {
  switch (phase) {
    case "uploading": {
      if (uploadProgress == null) {
        return "Uploading…";
      }
      const pct = Math.max(0, Math.min(100, Math.round(uploadProgress * 100)));
      return `Uploading… ${pct}%`;
    }
    case "processing":
      return "Processing photo…";
    case "approved":
      return "Photo approved";
    case "rejected":
      return "Photo rejected. Try another image.";
    case "retry":
      return "Upload failed. Tap to retry.";
    default:
      return null;
  }
}

export function resolveProfilePhotoMimeType(params: {
  mimeType?: string | null;
  fileName?: string | null;
  uri: string;
}): string | null {
  const declared = params.mimeType?.toLowerCase().trim();
  if (declared && PROFILE_PHOTO_ALLOWED_MIME.has(declared)) {
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
  return null;
}

export function validateProfilePhotoSelection(params: {
  uri: string;
  mimeType: string | null;
  byteSize: number | null;
  width?: number | null;
  height?: number | null;
}): { ok: true; asset: SelectedProfilePhoto } | { ok: false; message: string } {
  if (!params.uri) {
    return { ok: false, message: "Selected media has no file URI." };
  }
  if (!params.mimeType || !PROFILE_PHOTO_ALLOWED_MIME.has(params.mimeType)) {
    return {
      ok: false,
      message: "Only JPEG, PNG, or WebP images are supported.",
    };
  }
  if (params.byteSize == null || params.byteSize <= 0) {
    return { ok: false, message: "Could not determine the file size." };
  }
  if (params.byteSize > PROFILE_PHOTO_MAX_BYTES) {
    return {
      ok: false,
      message: `Profile photo must be ${Math.floor(PROFILE_PHOTO_MAX_BYTES / 1_000_000)} MB or smaller.`,
    };
  }
  return {
    ok: true,
    asset: {
      uri: params.uri,
      mimeType: params.mimeType,
      byteSize: params.byteSize,
      width: params.width ?? null,
      height: params.height ?? null,
    },
  };
}

export function mapCompleteResponseToPhase(params: {
  moderationStatus: string;
  published: boolean;
}): ProfilePhotoPhase {
  if (params.moderationStatus === "rejected") {
    return "rejected";
  }
  if (params.moderationStatus === "approved" && params.published) {
    return "approved";
  }
  if (params.moderationStatus === "approved") {
    return "processing";
  }
  return "processing";
}

/** After approval, client should refresh /v1/me so the new photo URL appears. */
export function shouldRefreshMeAfterPhase(phase: ProfilePhotoPhase): boolean {
  return phase === "approved";
}
