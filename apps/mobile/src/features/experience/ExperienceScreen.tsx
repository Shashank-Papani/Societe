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
import {
  loadDevFixtureJpeg,
  mapLifecycleToPhase,
  pickImageFromLibrary,
  uploadFileViaFileSystem,
  type SelectedMediaAsset,
  type UploadPhase,
} from "@/features/experience/uploadHelpers";
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

function phaseLabel(phase: UploadPhase): string {
  switch (phase) {
    case "idle":
      return "Ready";
    case "picking":
      return "Opening photo library…";
    case "permission_denied":
      return "Photo library permission denied";
    case "cancelled":
      return "Selection cancelled";
    case "validating":
      return "Validating selected image…";
    case "creating_intent":
      return "Creating upload intent…";
    case "uploading":
      return "Uploading to storage…";
    case "completing":
      return "Confirming upload…";
    case "processing":
      return "Processing and moderating…";
    case "published":
      return "Published to the venue feed";
    case "rejected":
      return "Rejected by validation or moderation";
    case "failed_retryable":
      return "Failed — you can retry";
    case "failed_permanent":
      return "Failed";
    default:
      return phase;
  }
}

export function ExperienceScreen() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [caption, setCaption] = useState("");
  const [uploadStatus, setUploadStatus] = useState<UploadStatus | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [previewUri, setPreviewUri] = useState<string | null>(null);

  const presenceQuery = useQuery({
    queryKey: ["presence", "me"],
    queryFn: fetchPresenceMe,
    enabled: auth.status === "authenticated",
    refetchInterval: 30_000,
  });

  const venueId = presenceQuery.data?.venue?.id ?? null;
  const venueName = presenceQuery.data?.venue?.name ?? null;
  const canPost = presenceQuery.data?.state === "verified" && Boolean(venueId);

  const feedQuery = useQuery({
    queryKey: ["vibes", venueId],
    queryFn: () => fetchVenueVibes(String(venueId)),
    enabled: auth.status === "authenticated" && Boolean(venueId),
    refetchInterval: 15_000,
  });

  useEffect(() => {
    // Phase is updated at mutation call sites and inside the poll callback.
    // Avoid syncing phase via setState in this effect (react-hooks/set-state-in-effect).
    if (!uploadStatus || TERMINAL.has(uploadStatus.lifecycle_status)) {
      return;
    }
    const timer = setInterval(() => {
      void fetchUploadStatus(uploadStatus.upload_id)
        .then((next) => {
          setUploadStatus(next);
          const nextPhase = mapLifecycleToPhase(
            next.lifecycle_status,
            next.publication_status,
          );
          setPhase(nextPhase);
          if (nextPhase === "published") {
            void queryClient.invalidateQueries({ queryKey: ["vibes", venueId] });
          }
        })
        .catch((error: Error) => {
          setUploadError(error.message);
          setPhase("failed_retryable");
        });
    }, 2_500);
    return () => clearInterval(timer);
  }, [uploadStatus, venueId, queryClient]);

  const runUpload = async (asset: SelectedMediaAsset) => {
    if (!venueId) {
      throw new Error("Verify presence at a venue before posting.");
    }
    setPreviewUri(asset.uri);
    setUploadError(null);
    setUploadProgress(null);
    setPhase("creating_intent");

    const intent = await createMediaUpload({
      venueId,
      mediaType: asset.mediaType,
      mimeType: asset.mimeType,
      byteSize: asset.byteSize,
      caption: caption.trim() || undefined,
    });

    setPhase("uploading");
    await uploadFileViaFileSystem({
      uploadUrl: intent.upload.url,
      fileUri: asset.uri,
      headers: intent.upload.headers,
      onProgress: (fraction) => setUploadProgress(fraction),
    });

    setPhase("completing");
    const status = await completeMediaUpload(intent.upload_id);
    setUploadStatus(status);
    setPhase(mapLifecycleToPhase(status.lifecycle_status, status.publication_status));
    setCaption("");
    return status;
  };

  const galleryMutation = useMutation({
    mutationFn: async () => {
      if (!canPost || !venueId) {
        throw new Error("Verify presence at a venue before posting.");
      }
      setPhase("picking");
      setUploadError(null);
      const picked = await pickImageFromLibrary();
      if (picked.status === "permission_denied") {
        setPhase("permission_denied");
        throw new Error("Photo library permission is required to post a Live Vibe.");
      }
      if (picked.status === "cancelled") {
        setPhase("cancelled");
        throw new Error("CANCELLED");
      }
      if (picked.status === "invalid") {
        setPhase("failed_permanent");
        throw new Error(picked.message);
      }
      setPhase("validating");
      return runUpload(picked.asset);
    },
    onError: (error: Error) => {
      if (error.message === "CANCELLED") {
        setUploadError(null);
        return;
      }
      setUploadError(error.message);
      if (phase !== "permission_denied" && phase !== "cancelled") {
        setPhase("failed_retryable");
      }
    },
  });

  const fixtureMutation = useMutation({
    mutationFn: async () => {
      if (!canPost || !venueId) {
        throw new Error("Verify presence at a venue before posting.");
      }
      setPhase("validating");
      const asset = await loadDevFixtureJpeg();
      return runUpload(asset);
    },
    onError: (error: Error) => {
      setUploadError(error.message);
      setPhase("failed_retryable");
    },
  });

  const reportMutation = useMutation({
    mutationFn: (vibeId: string) => reportVibe(vibeId, "other"),
  });

  const busy = galleryMutation.isPending || fixtureMutation.isPending;
  const showRetry =
    phase === "failed_retryable" || phase === "rejected" || phase === "failed_permanent";

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
          <Text style={styles.meta}>Venue: {venueName ?? "none"}</Text>
        </View>
      ) : null}

      {canPost ? (
        <View style={styles.card}>
          <Text style={styles.section}>Post a Live Vibe</Text>
          <Text style={styles.help}>
            Choose a photo from your library. The server validates size, type,
            presence, and moderation before the vibe appears in the feed.
          </Text>
          <TextInput
            style={styles.input}
            placeholder="Caption (optional)"
            placeholderTextColor="#6f7c99"
            value={caption}
            onChangeText={setCaption}
            maxLength={300}
            editable={!busy}
          />
          {previewUri ? (
            <Image source={{ uri: previewUri }} style={styles.localPreview} contentFit="cover" />
          ) : null}
          <Pressable
            style={[styles.button, busy && styles.buttonDisabled]}
            disabled={busy}
            onPress={() => galleryMutation.mutate()}
          >
            <Text style={styles.buttonText}>
              {busy && phase === "picking" ? "Opening library…" : "Choose from library"}
            </Text>
          </Pressable>
          {showRetry ? (
            <Pressable
              style={[styles.buttonSecondary, busy && styles.buttonDisabled]}
              disabled={busy}
              onPress={() => galleryMutation.mutate()}
            >
              <Text style={styles.buttonSecondaryText}>Retry upload</Text>
            </Pressable>
          ) : null}
          {__DEV__ ? (
            <Pressable
              style={[styles.buttonSecondary, busy && styles.buttonDisabled]}
              disabled={busy}
              onPress={() => fixtureMutation.mutate()}
            >
              <Text style={styles.buttonSecondaryText}>
                Dev only: upload bundled fixture JPEG
              </Text>
            </Pressable>
          ) : null}
        </View>
      ) : (
        <Text style={styles.help}>
          Verify at a venue on the Presence tab to unlock posting. You can still
          browse a venue feed from Discover without being there.
        </Text>
      )}

      {phase !== "idle" ? (
        <View style={styles.card}>
          <Text style={styles.section}>Status</Text>
          <Text style={styles.meta}>{phaseLabel(phase)}</Text>
          {uploadProgress != null && phase === "uploading" ? (
            <Text style={styles.meta}>
              Upload progress: {Math.round(uploadProgress * 100)}%
            </Text>
          ) : null}
          {busy ? <ActivityIndicator color="#9aa6bf" style={{ marginTop: 8 }} /> : null}
        </View>
      ) : null}

      {uploadError ? <Text style={styles.error}>{uploadError}</Text> : null}
      {uploadStatus ? (
        <View style={styles.card}>
          <Text style={styles.section}>Server status</Text>
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

      <Text style={styles.section}>Venue feed{venueName ? ` · ${venueName}` : ""}</Text>
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
  buttonSecondary: {
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#334155",
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: "#f5f7fb", fontWeight: "600" },
  buttonSecondaryText: { color: "#cbd5e1", fontWeight: "500" },
  localPreview: { width: "100%", height: 160, borderRadius: 10, backgroundColor: "#0b1220" },
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
