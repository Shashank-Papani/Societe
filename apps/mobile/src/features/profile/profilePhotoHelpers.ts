/**
 * Profile photo gallery pick + FileSystem PUT.
 * Bytes go from a file URI to object storage via uploadAsync — no Blob /
 * ArrayBuffer / Uint8Array / atob / base64 paths. Live Vibes helpers are not used.
 */

import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";

import {
  resolveProfilePhotoMimeType,
  validateProfilePhotoSelection,
  type SelectedProfilePhoto,
} from "@/features/profile/profilePhotoUi";

export type ProfilePhotoPickResult =
  | { status: "selected"; asset: SelectedProfilePhoto }
  | { status: "cancelled" }
  | { status: "permission_denied" }
  | { status: "invalid"; message: string };

async function readFileSize(uri: string): Promise<number | null> {
  const info = await FileSystem.getInfoAsync(uri);
  if (!info.exists || info.isDirectory || typeof info.size !== "number") {
    return null;
  }
  return info.size;
}

export async function pickProfilePhotoFromLibrary(): Promise<ProfilePhotoPickResult> {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!permission.granted) {
    return { status: "permission_denied" };
  }

  const picked = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    quality: 1,
    exif: false,
    allowsMultipleSelection: false,
  });

  if (picked.canceled || !picked.assets[0]) {
    return { status: "cancelled" };
  }

  const asset = picked.assets[0];
  const mimeType = resolveProfilePhotoMimeType({
    mimeType: asset.mimeType,
    fileName: asset.fileName,
    uri: asset.uri,
  });

  let byteSize =
    typeof asset.fileSize === "number" && asset.fileSize > 0 ? asset.fileSize : null;
  if (byteSize == null) {
    byteSize = await readFileSize(asset.uri);
  }

  const validated = validateProfilePhotoSelection({
    uri: asset.uri,
    mimeType,
    byteSize,
    width: asset.width,
    height: asset.height,
  });
  if (!validated.ok) {
    return { status: "invalid", message: validated.message };
  }
  return { status: "selected", asset: validated.asset };
}

export async function uploadProfilePhotoViaFileSystem(params: {
  uploadUrl: string;
  fileUri: string;
  headers: Record<string, string>;
  onProgress?: (fraction: number) => void;
}): Promise<void> {
  params.onProgress?.(0);
  const result = await FileSystem.uploadAsync(params.uploadUrl, params.fileUri, {
    httpMethod: "PUT",
    uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
    headers: params.headers,
  });
  params.onProgress?.(1);

  if (result.status < 200 || result.status >= 300) {
    throw new Error(`Profile photo upload failed with status ${result.status}`);
  }
}
