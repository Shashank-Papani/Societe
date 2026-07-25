import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import * as FileSystem from "expo-file-system/legacy";

import { useAuth } from "@/auth/AuthProvider";
import {
  completeMediaUpload,
  createMediaUpload,
  fetchUploadStatus,
  fetchVenueVibes,
  reportVibe,
  type UploadStatus,
  type VibeFeedItem,
} from "@/features/experience/api";
import { fetchPresenceMe } from "@/features/presence/api";

const TERMINAL = new Set([
  "ready",
  "invalid",
  "rejected",
  "processing_failed",
  "upload_expired",
  "revoked",
  "deleted",
]);

const SAMPLE_JPEG_BASE64 =
  "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAIAAQDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAGcA//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAQUCf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8Bf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8Bf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEABj8Cf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8hf//Z";

async function createSampleJpegFile(): Promise<{
  uri: string;
  size: number;
}> {
  const cacheDirectory = FileSystem.cacheDirectory;

  if (!cacheDirectory) {
    throw new Error("File-system cache directory is unavailable.");
  }

  const uri = `${cacheDirectory}societe-vibe-${Date.now()}.jpg`;

  await FileSystem.writeAsStringAsync(uri, SAMPLE_JPEG_BASE64, {
    encoding: FileSystem.EncodingType.Base64,
  });

  const info = await FileSystem.getInfoAsync(uri);

  if (
    !info.exists ||
    info.isDirectory ||
    typeof info.size !== "number"
  ) {
    await FileSystem.deleteAsync(uri, {
      idempotent: true,
    }).catch(() => undefined);

    throw new Error("Could not create the sample JPEG fixture.");
  }

  return {
    uri,
    size: info.size,
  };
}

async function uploadFile(params: {
  uploadUrl: string;
  fileUri: string;
  headers: Record<string, string>;
}): Promise<void> {
  const result = await FileSystem.uploadAsync(
    params.uploadUrl,
    params.fileUri,
    {
      httpMethod: "PUT",
      uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
      headers: params.headers,
    },
  );

  if (result.status < 200 || result.status >= 300) {
    throw new Error(
      `Media upload failed with status ${result.status}: ${result.body}`,
    );
  }
}

export function ExperienceScreen() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [caption, setCaption] = useState("");
  const [uploadStatus, setUploadStatus] = useState<UploadStatus | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const presenceQuery = useQuery({
    queryKey: ["presence", "me"],
    queryFn: fetchPresenceMe,
    enabled: auth.status === "authenticated",
    refetchInterval: 30_000,
  });

  const venueId = presenceQuery.data?.venue?.id ?? null;
  const canPost = presenceQuery.data?.state === "verified" && Boolean(venueId);

  const feedQuery = useQuery({
    queryKey: ["vibes", venueId],
    queryFn: () => fetchVenueVibes(String(venueId)),
    enabled: auth.status === "authenticated" && Boolean(venueId),
    refetchInterval: 15_000,
  });

  useEffect(() => {
    if (!uploadStatus || TERMINAL.has(uploadStatus.lifecycle_status)) {
      return;
    }
    const timer = setInterval(() => {
      void fetchUploadStatus(uploadStatus.upload_id)
        .then((next) => {
          setUploadStatus(next);
          if (next.lifecycle_status === "ready" || next.publication_status === "published") {
            void queryClient.invalidateQueries({ queryKey: ["vibes", venueId] });
          }
        })
        .catch((error: Error) => setUploadError(error.message));
    }, 2_500);
    return () => clearInterval(timer);
  }, [uploadStatus, venueId, queryClient]);

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!venueId) {
        throw new Error("Verify presence at a venue before posting.");
      }
  
      const sampleFile = await createSampleJpegFile();
  
      try {
        const intent = await createMediaUpload({
          venueId,
          mediaType: "image",
          mimeType: "image/jpeg",
          byteSize: sampleFile.size,
          caption: caption.trim() || undefined,
        });
  
        await uploadFile({
          uploadUrl: intent.upload.url,
          fileUri: sampleFile.uri,
          headers: intent.upload.headers,
        });
  
        return await completeMediaUpload(intent.upload_id);
      } finally {
        await FileSystem.deleteAsync(sampleFile.uri, {
          idempotent: true,
        }).catch(() => undefined);
      }
    },
  
    onSuccess: (status) => {
      setUploadError(null);
      setUploadStatus(status);
      setCaption("");
    },
  
    onError: (error: Error) => {
      setUploadError(error.message);
    },
  });

  const reportMutation = useMutation({
    mutationFn: (vibeId: string) => reportVibe(vibeId, "other"),
  });

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.title}>Experience</Text>
      <Text style={styles.subtitle}>Live Vibes at your verified venue</Text>

      {auth.status === "initializing" || presenceQuery.isLoading ? (
        <ActivityIndicator color="#9aa6bf" />
      ) : null}
      {auth.status === "unauthenticated" ? (
        <Text style={styles.help}>Sign in on Profile, then verify presence to post.</Text>
      ) : null}

      {presenceQuery.data ? (
        <View style={styles.card}>
          <Text style={styles.meta}>Presence: {presenceQuery.data.state}</Text>
          <Text style={styles.meta}>Venue: {presenceQuery.data.venue?.name ?? "none"}</Text>
        </View>
      ) : null}

      {canPost ? (
        <View style={styles.card}>
          <Text style={styles.section}>Post a Live Vibe</Text>
          <Text style={styles.help}>
            Phase 3 local build posts a synthetic JPEG fixture. Library picker
            wiring can replace this without changing the upload API.
          </Text>
          <TextInput
            style={styles.input}
            placeholder="Caption (optional)"
            placeholderTextColor="#6f7c99"
            value={caption}
            onChangeText={setCaption}
            maxLength={300}
          />
          <Pressable
            style={[styles.button, uploadMutation.isPending && styles.buttonDisabled]}
            disabled={uploadMutation.isPending}
            onPress={() => uploadMutation.mutate()}
          >
            <Text style={styles.buttonText}>
              {uploadMutation.isPending ? "Uploading…" : "Upload sample photo"}
            </Text>
          </Pressable>
        </View>
      ) : (
        <Text style={styles.help}>
          Verify at a venue on the Presence tab to unlock posting. You can still
          browse a venue feed from Discover without being there.
        </Text>
      )}

      {uploadError ? <Text style={styles.error}>{uploadError}</Text> : null}
      {uploadStatus ? (
        <View style={styles.card}>
          <Text style={styles.section}>Upload status</Text>
          <Text style={styles.meta}>lifecycle: {uploadStatus.lifecycle_status}</Text>
          <Text style={styles.meta}>moderation: {uploadStatus.moderation_status}</Text>
          <Text style={styles.meta}>
            publication: {uploadStatus.publication_status ?? "—"}
          </Text>
          {uploadStatus.failure_reason ? (
            <Text style={styles.error}>{uploadStatus.failure_reason}</Text>
          ) : null}
        </View>
      ) : null}

      <Text style={styles.section}>Venue feed</Text>
      {!venueId ? (
        <Text style={styles.help}>No current venue — open a venue from Discover to browse.</Text>
      ) : null}
      {feedQuery.isLoading ? <ActivityIndicator color="#9aa6bf" /> : null}
      {feedQuery.error ? (
        <Text style={styles.error}>{(feedQuery.error as Error).message}</Text>
      ) : null}
      {(feedQuery.data?.items ?? []).map((item) => (
        <VibeRow
          key={item.id}
          item={item}
          onReport={() => reportMutation.mutate(item.id)}
          reporting={reportMutation.isPending}
        />
      ))}
      {venueId && feedQuery.data?.items.length === 0 ? (
        <Text style={styles.help}>No published Live Vibes yet.</Text>
      ) : null}
    </ScrollView>
  );
}

function VibeRow({
  item,
  onReport,
  reporting,
}: {
  item: VibeFeedItem;
  onReport: () => void;
  reporting: boolean;
}) {
  const preview =
    item.variants.find((v) => v.variant_type === "image_720" || v.variant_type === "thumbnail") ??
    item.variants.find((v) => v.variant_type === "video_poster") ??
    item.variants[0];

  return (
    <View style={styles.vibe}>
      {preview ? (
        <Image source={{ uri: preview.url }} style={styles.preview} contentFit="cover" />
      ) : (
        <View style={[styles.preview, styles.previewEmpty]}>
          <Text style={styles.meta}>{item.media_type}</Text>
        </View>
      )}
      <Text style={styles.author}>{item.author_label}</Text>
      {item.caption ? <Text style={styles.caption}>{item.caption}</Text> : null}
      <Text style={styles.meta}>
        {item.attribution_mode}
        {item.viewer_is_author ? " · you" : ""}
      </Text>
      {!item.viewer_is_author ? (
        <Pressable style={styles.report} onPress={onReport} disabled={reporting}>
          <Text style={styles.reportText}>Report</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b1220" },
  content: { padding: 20, gap: 12, paddingBottom: 64 },
  brand: { color: "#f5f7fb", fontSize: 28, fontWeight: "700", letterSpacing: 0.4 },
  title: { color: "#f5f7fb", fontSize: 22, fontWeight: "600" },
  subtitle: { color: "#9aa6bf", marginBottom: 8 },
  section: { color: "#f5f7fb", fontSize: 16, fontWeight: "600", marginTop: 8 },
  help: { color: "#9aa6bf", lineHeight: 20 },
  error: { color: "#f87171" },
  card: {
    gap: 8,
    padding: 14,
    borderRadius: 12,
    backgroundColor: "#121a2b",
    borderColor: "#1e293b",
    borderWidth: 1,
  },
  meta: { color: "#9aa6bf", fontSize: 13 },
  input: {
    borderWidth: 1,
    borderColor: "#1e293b",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: "#f5f7fb",
  },
  button: {
    backgroundColor: "#2563eb",
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: "#f5f7fb", fontWeight: "600" },
  vibe: {
    gap: 6,
    paddingBottom: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#1e293b",
  },
  preview: { width: "100%", height: 220, borderRadius: 12, backgroundColor: "#121a2b" },
  previewEmpty: { alignItems: "center", justifyContent: "center" },
  author: { color: "#f5f7fb", fontWeight: "600" },
  caption: { color: "#d7deee" },
  report: { alignSelf: "flex-start", paddingVertical: 4 },
  reportText: { color: "#f87171", fontSize: 13 },
});
