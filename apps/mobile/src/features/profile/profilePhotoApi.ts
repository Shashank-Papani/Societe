import { z } from "zod";

import { apiFetch } from "@/api/client";
import { getStoredDeviceId } from "@/auth/deviceStore";

const createSchema = z.object({
  upload_id: z.string(),
  upload_url: z.string(),
  headers: z.record(z.string(), z.string()),
  expires_at: z.string(),
  moderation_status: z.string(),
});

const completeSchema = z.object({
  upload_id: z.string(),
  moderation_status: z.string(),
  lifecycle_status: z.string(),
  published: z.boolean(),
});

export type ProfilePhotoUploadIntent = z.infer<typeof createSchema>;
export type ProfilePhotoCompleteResult = z.infer<typeof completeSchema>;

export async function createProfilePhotoUpload(input: {
  mimeType: string;
  byteSize: number;
}): Promise<ProfilePhotoUploadIntent> {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) {
    throw new Error("Register a device first (sign in again).");
  }
  const envelope = await apiFetch<z.infer<typeof createSchema>>("/v1/me/profile-photo/uploads", {
    method: "POST",
    body: JSON.stringify({
      device_id: deviceId,
      mime_type: input.mimeType,
      byte_size: input.byteSize,
    }),
  });
  return createSchema.parse(envelope.data);
}

export async function completeProfilePhotoUpload(
  uploadId: string,
): Promise<ProfilePhotoCompleteResult> {
  const envelope = await apiFetch<z.infer<typeof completeSchema>>(
    `/v1/me/profile-photo/uploads/${uploadId}/complete`,
    { method: "POST" },
  );
  return completeSchema.parse(envelope.data);
}
