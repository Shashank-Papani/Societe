/**
 * Client-side helpers for Live Vibe gallery uploads.
 *
 * Bytes go straight from a file URI to MinIO via expo-file-system uploadAsync.
 * No Blob / ArrayBuffer / Uint8Array / atob / base64 round trips.
 */

import { Asset } from "expo-asset";
import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";

import {
  resolveImageMimeType,
  validateSelectedImage,
  type SelectedMediaAsset,
  type UploadPhase,
} from "@/features/experience/mediaValidation";

export type { SelectedMediaAsset, UploadPhase };
export {
  ALLOWED_IMAGE_MIME,
  MAX_IMAGE_BYTES,
  MAX_IMAGE_EDGE,
  mapLifecycleToPhase,
  resolveImageMimeType,
  validateSelectedImage,
} from "@/features/experience/mediaValidation";

export type PickResult =
  | { status: "selected"; asset: SelectedMediaAsset }
  | { status: "cancelled" }
  | { status: "permission_denied" }
  | { status: "invalid"; message: string };

export async function readFileSize(uri: string): Promise<number | null> {
  // Legacy getInfoAsync always includes `size` when the path exists as a file.
  const info = await FileSystem.getInfoAsync(uri);
  if (!info.exists || info.isDirectory || typeof info.size !== "number") {
    return null;
  }
  return info.size;
}

export async function pickImageFromLibrary(): Promise<PickResult> {
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
  return { status: "selected", asset: validated.asset };
}

/**
 * Development-only fixture: copies the bundled real JPEG into cache and returns
 * a file URI. Explicitly labeled in the UI — never the default posting path.
 */
export async function loadDevFixtureJpeg(): Promise<SelectedMediaAsset> {
  if (!__DEV__) {
    throw new Error("Dev fixture is only available in development builds.");
  }
  const cacheDirectory = FileSystem.cacheDirectory;
  if (!cacheDirectory) {
    throw new Error("File-system cache directory is unavailable.");
  }

  // Bundled asset — Metro resolves this to a packager asset, not a base64 string.
  const moduleId = require("../../../assets/fixtures/sample-vibe.jpg") as number;
  const asset = Asset.fromModule(moduleId);
  await asset.downloadAsync();
  const localUri = asset.localUri ?? asset.uri;
  if (!localUri) {
    throw new Error("Dev fixture JPEG could not be resolved to a local URI.");
  }

  const destination = `${cacheDirectory}societe-dev-fixture-${Date.now()}.jpg`;
  await FileSystem.copyAsync({ from: localUri, to: destination });
  const size = await readFileSize(destination);
  const validated = validateSelectedImage({
    uri: destination,
    mimeType: "image/jpeg",
    byteSize: size,
    width: asset.width || 800,
    height: asset.height || 1000,
  });
  if (!validated.ok) {
    throw new Error(validated.message);
  }
  return validated.asset;
}

export async function uploadFileViaFileSystem(params: {
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
    throw new Error(`Media upload failed with status ${result.status}: ${result.body}`);
  }
}
