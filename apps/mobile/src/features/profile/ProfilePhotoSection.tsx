import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as FileSystem from "expo-file-system/legacy";
import { useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { fetchMe } from "@/auth/localAuth";
import { ProfilePhotoCropEditor } from "@/features/profile/ProfilePhotoCropEditor";
import {
  completeProfilePhotoUpload,
  createProfilePhotoUpload,
} from "@/features/profile/profilePhotoApi";
import {
  pickProfilePhotoFromLibrary,
  uploadProfilePhotoViaFileSystem,
} from "@/features/profile/profilePhotoHelpers";
import {
  resolveUploadUri,
  shouldUploadOnCancel,
} from "@/features/profile/profilePhotoCropMath";
import {
  chooseOrReplaceLabel,
  mapCompleteResponseToPhase,
  profilePhotoStatusLabel,
  resolveVisibleProfilePhoto,
  shouldRefreshMeAfterPhase,
  type ProfilePhotoPhase,
  type SelectedProfilePhoto,
} from "@/features/profile/profilePhotoUi";

type Props = {
  approvedUrl: string | null | undefined;
};

type EditorSource = {
  uri: string;
  width: number;
  height: number;
};

async function readByteSize(uri: string): Promise<number> {
  const info = await FileSystem.getInfoAsync(uri);
  if (!info.exists || info.isDirectory || typeof info.size !== "number" || info.size <= 0) {
    throw new Error("Could not determine cropped photo size.");
  }
  return info.size;
}

export function ProfilePhotoSection({ approvedUrl }: Props) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<ProfilePhotoPhase>("idle");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastCropped, setLastCropped] = useState<SelectedProfilePhoto | null>(null);
  const [editorSource, setEditorSource] = useState<EditorSource | null>(null);

  const display = resolveVisibleProfilePhoto({ approvedUrl, phase });
  const actionLabel = chooseOrReplaceLabel(display.hasApprovedPhoto);
  const status = profilePhotoStatusLabel(phase, uploadProgress);
  const busy = phase === "uploading" || phase === "processing";

  const runUpload = async (asset: SelectedProfilePhoto) => {
    setLastCropped(asset);
    setError(null);
    setUploadProgress(null);
    setPhase("uploading");

    const intent = await createProfilePhotoUpload({
      mimeType: asset.mimeType,
      byteSize: asset.byteSize,
    });

    await uploadProfilePhotoViaFileSystem({
      uploadUrl: intent.upload_url,
      fileUri: asset.uri,
      headers: intent.headers,
      onProgress: (fraction) => setUploadProgress(fraction),
    });

    setPhase("processing");
    setUploadProgress(null);
    const completed = await completeProfilePhotoUpload(intent.upload_id);
    const nextPhase = mapCompleteResponseToPhase({
      moderationStatus: completed.moderation_status,
      published: completed.published,
    });
    setPhase(nextPhase);

    if (shouldRefreshMeAfterPhase(nextPhase)) {
      const me = await fetchMe();
      queryClient.setQueryData(["me"], me);
    }
  };

  const pickMutation = useMutation({
    mutationFn: async () => {
      const picked = await pickProfilePhotoFromLibrary();
      if (picked.status === "permission_denied") {
        throw new Error("Photo library permission is required.");
      }
      if (picked.status === "cancelled") {
        if (shouldUploadOnCancel()) {
          throw new Error("Unexpected upload after cancel.");
        }
        throw new Error("CANCELLED");
      }
      if (picked.status === "invalid") {
        setPhase("rejected");
        throw new Error(picked.message);
      }
      const width = picked.asset.width;
      const height = picked.asset.height;
      if (width == null || height == null || width <= 0 || height <= 0) {
        throw new Error("Selected photo is missing dimensions.");
      }
      // Open editor — do not upload the original gallery URI.
      setEditorSource({ uri: picked.asset.uri, width, height });
      setError(null);
      setPhase("idle");
    },
    onError: (err: Error) => {
      if (err.message === "CANCELLED") {
        setError(null);
        setPhase("idle");
        return;
      }
      setError(err.message);
      setPhase((current) => (current === "rejected" ? current : "retry"));
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (asset: SelectedProfilePhoto) => runUpload(asset),
    onError: (err: Error) => {
      setError(err.message);
      setPhase("retry");
    },
  });

  const onEditorCancel = () => {
    setEditorSource(null);
    setError(null);
    setPhase("idle");
  };

  const onEditorUsePhoto = async (cropped: {
    uri: string;
    mimeType: "image/jpeg";
    width: number;
    height: number;
  }) => {
    const uploadUri = resolveUploadUri({
      originalUri: editorSource?.uri ?? "",
      croppedUri: cropped.uri,
    });
    if (!uploadUri) {
      setError("Cropped photo missing.");
      return;
    }
    try {
      const byteSize = await readByteSize(uploadUri);
      const asset: SelectedProfilePhoto = {
        uri: uploadUri,
        mimeType: "image/jpeg",
        byteSize,
        width: cropped.width,
        height: cropped.height,
      };
      // Close editor after successful crop export; upload failures retry the cropped URI.
      setLastCropped(asset);
      setEditorSource(null);
      setError(null);
      uploadMutation.mutate(asset);
    } catch (err) {
      // Failed crop export / size read: keep editor open for Retry.
      setError(err instanceof Error ? err.message : "Could not prepare cropped photo.");
    }
  };

  const onPrimaryPress = () => {
    if (phase === "retry" && lastCropped) {
      uploadMutation.mutate(lastCropped);
      return;
    }
    pickMutation.mutate();
  };

  return (
    <View style={styles.section}>
      <Text style={styles.heading}>Edit Profile</Text>
      <Text style={styles.label}>Profile Photo</Text>
      <Text style={styles.help}>Optional. You can skip this and change it later.</Text>

      <View style={styles.previewRow}>
        {display.mode === "remote" && display.uri ? (
          <Image source={{ uri: display.uri }} style={styles.avatar} accessibilityLabel="Profile photo" />
        ) : (
          <View
            style={[styles.avatar, styles.placeholder]}
            accessibilityLabel={
              display.mode === "approved_marker" ? "Approved profile photo" : "No profile photo"
            }
          >
            <Text style={styles.placeholderText}>
              {display.mode === "approved_marker" ? "Photo" : "No photo"}
            </Text>
          </View>
        )}
        <View style={styles.previewMeta}>
          {status ? <Text style={styles.status}>{status}</Text> : null}
          {busy ? <ActivityIndicator color="#9aa6bf" /> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>
      </View>

      <Pressable
        style={[styles.button, busy || pickMutation.isPending ? styles.buttonDisabled : null]}
        disabled={busy || pickMutation.isPending || uploadMutation.isPending}
        onPress={onPrimaryPress}
      >
        <Text style={styles.buttonText}>
          {phase === "retry" && lastCropped ? "Retry upload" : actionLabel}
        </Text>
      </Pressable>

      {editorSource ? (
        <ProfilePhotoCropEditor
          visible
          uri={editorSource.uri}
          imageWidth={editorSource.width}
          imageHeight={editorSource.height}
          onCancel={onEditorCancel}
          onUsePhoto={(cropped) => {
            void onEditorUsePhoto(cropped);
          }}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { gap: 8, marginBottom: 8 },
  heading: { fontSize: 18, fontWeight: "600", color: "#f5f7fb", marginTop: 4 },
  label: { fontSize: 16, fontWeight: "600", color: "#f5f7fb" },
  help: { color: "#9aa6bf", fontSize: 13, lineHeight: 18 },
  previewRow: { flexDirection: "row", alignItems: "center", gap: 14, marginVertical: 4 },
  avatar: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: "#1e293b",
  },
  placeholder: {
    alignItems: "center",
    justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "#334155",
  },
  placeholderText: { color: "#6f7c99", fontSize: 12, fontWeight: "600" },
  previewMeta: { flex: 1, gap: 6 },
  status: { color: "#9aa6bf", fontSize: 14 },
  error: { color: "#fca5a5", fontSize: 13 },
  button: {
    backgroundColor: "#3b82f6",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: "center",
  },
  buttonDisabled: { opacity: 0.55 },
  buttonText: { color: "#fff", fontWeight: "600" },
});
