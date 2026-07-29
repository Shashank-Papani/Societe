/**
 * Lightweight pending Story upload recovery.
 * Persists upload_id only — never signed URLs or tokens.
 */

import * as SecureStore from "expo-secure-store";

const KEY = "societe.pending_story_upload_v1";

export type PendingStoryUpload = {
  uploadId: string;
  storyId: string;
  venueId: string;
  idempotencyKey: string;
  updatedAt: string;
};

export async function savePendingStoryUpload(
  value: PendingStoryUpload,
): Promise<void> {
  await SecureStore.setItemAsync(KEY, JSON.stringify(value));
}

export async function loadPendingStoryUpload(): Promise<PendingStoryUpload | null> {
  const raw = await SecureStore.getItemAsync(KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as PendingStoryUpload;
    if (
      typeof parsed.uploadId !== "string" ||
      typeof parsed.storyId !== "string" ||
      typeof parsed.venueId !== "string" ||
      typeof parsed.idempotencyKey !== "string"
    ) {
      await clearPendingStoryUpload();
      return null;
    }
    return parsed;
  } catch {
    await clearPendingStoryUpload();
    return null;
  }
}

export async function clearPendingStoryUpload(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY);
}
