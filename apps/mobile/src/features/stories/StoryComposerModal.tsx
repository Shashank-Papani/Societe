import * as Crypto from "expo-crypto";
import { Image } from "expo-image";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError } from "@/api/client";
import {
  completeUserStoryUpload,
  createUserStoryUpload,
  fetchStoryUploadStatus,
  type StoryUploadResponse,
} from "@/features/stories/api";
import {
  clearPendingStoryUpload,
  loadPendingStoryUpload,
  savePendingStoryUpload,
} from "@/features/stories/pendingStoryUpload";
import {
  isStoryUploadTerminal,
  mapStoryUploadPhase,
  type StoryUploadPhase,
} from "@/features/stories/storyHelpers";
import {
  pickStoryMediaFromLibrary,
  type StorySelectedMedia,
} from "@/features/stories/storyMedia";
import { uploadFileViaFileSystem } from "@/features/experience/uploadHelpers";
import { colors, fontFamilies, radii, spacing } from "@/theme";

const SUGGESTED_TAGS = ["nightlife", "live", "music", "dance", "crowd"];

type Props = {
  visible: boolean;
  venueId: string;
  venueName: string;
  onClose: () => void;
  onPublished: () => void;
  /** When false (logout), stop polling and clear local pending state. */
  sessionActive: boolean;
};

function phaseLabel(phase: StoryUploadPhase, progress: number | null): string {
  switch (phase) {
    case "idle":
      return "Ready";
    case "picking":
      return "Opening library…";
    case "permission_denied":
      return "Photo library permission denied";
    case "cancelled":
      return "Cancelled";
    case "preparing":
      return "Preparing…";
    case "creating_intent":
      return "Creating upload…";
    case "uploading":
      return progress != null
        ? `Uploading… ${Math.round(progress * 100)}%`
        : "Uploading…";
    case "completing":
      return "Verifying upload…";
    case "processing":
      return "Processing…";
    case "moderation_pending":
      return "Moderation pending…";
    case "published":
      return "Published";
    case "rejected":
      return "Rejected by moderation";
    case "failed":
      return "Upload failed";
    case "upload_expired":
      return "Upload expired";
    case "unavailable":
      return "Stories unavailable";
    default:
      return phase;
  }
}

export function StoryComposerModal({
  visible,
  venueId,
  venueName,
  onClose,
  onPublished,
  sessionActive,
}: Props) {
  const insets = useSafeAreaInsets();
  const [asset, setAsset] = useState<StorySelectedMedia | null>(null);
  const [caption, setCaption] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [attribution, setAttribution] = useState<"attributed" | "anonymous">(
    "attributed",
  );
  const [replyPolicy, setReplyPolicy] = useState<
    "disabled" | "connections" | "everyone"
  >("disabled");
  const [phase, setPhase] = useState<StoryUploadPhase>("idle");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<StoryUploadResponse | null>(
    null,
  );

  const idempotencyKeyRef = useRef<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!visible) {
      return;
    }
    cancelledRef.current = false;
    void (async () => {
      const pending = await loadPendingStoryUpload();
      if (!pending || pending.venueId !== venueId) {
        return;
      }
      idempotencyKeyRef.current = pending.idempotencyKey;
      setPhase("processing");
      try {
        const status = await fetchStoryUploadStatus(pending.uploadId);
        setUploadStatus(status);
        const next = mapStoryUploadPhase(
          status.lifecycle_status,
          status.publication_status,
          status.moderation_status,
        );
        setPhase(next);
        if (next === "published") {
          await clearPendingStoryUpload();
          onPublished();
        }
      } catch {
        // Leave composer idle if recovery fails — user can retry manually.
        setPhase("idle");
      }
    })();
  }, [visible, venueId, onPublished]);

  useEffect(() => {
    if (!sessionActive) {
      stopPolling();
      void clearPendingStoryUpload();
    }
  }, [sessionActive, stopPolling]);

  useEffect(() => {
    if (!visible || !uploadStatus || isStoryUploadTerminal(uploadStatus)) {
      stopPolling();
      return;
    }
    stopPolling();
    pollRef.current = setInterval(() => {
      void fetchStoryUploadStatus(uploadStatus.upload_id)
        .then(async (next) => {
          if (cancelledRef.current) {
            return;
          }
          setUploadStatus(next);
          const mapped = mapStoryUploadPhase(
            next.lifecycle_status,
            next.publication_status,
            next.moderation_status,
          );
          setPhase(mapped);
          if (mapped === "published") {
            stopPolling();
            await clearPendingStoryUpload();
            onPublished();
          } else if (isStoryUploadTerminal(next)) {
            stopPolling();
            await clearPendingStoryUpload();
          }
        })
        .catch(() => undefined);
    }, 2000);
    return stopPolling;
  }, [visible, uploadStatus, stopPolling, onPublished]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    const sub = AppState.addEventListener("change", (next) => {
      if (next === "active" && uploadStatus && !isStoryUploadTerminal(uploadStatus)) {
        void fetchStoryUploadStatus(uploadStatus.upload_id)
          .then((status) => {
            setUploadStatus(status);
            setPhase(
              mapStoryUploadPhase(
                status.lifecycle_status,
                status.publication_status,
                status.moderation_status,
              ),
            );
          })
          .catch(() => undefined);
      }
    });
    return () => sub.remove();
  }, [visible, uploadStatus]);

  useEffect(() => {
    return () => {
      cancelledRef.current = true;
      stopPolling();
    };
  }, [stopPolling]);

  const pickMedia = async () => {
    setError(null);
    setPhase("picking");
    const picked = await pickStoryMediaFromLibrary();
    if (picked.status === "cancelled") {
      setPhase(asset ? "idle" : "cancelled");
      return;
    }
    if (picked.status === "permission_denied") {
      setPhase("permission_denied");
      return;
    }
    if (picked.status === "invalid") {
      setPhase("failed");
      setError(picked.message);
      return;
    }
    setAsset(picked.asset);
    setPhase("idle");
  };

  const toggleTag = (tag: string) => {
    setTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag].slice(0, 5),
    );
  };

  const submit = async () => {
    if (!asset) {
      setError("Choose a photo or short video first.");
      return;
    }
    setError(null);
    if (!idempotencyKeyRef.current) {
      idempotencyKeyRef.current = Crypto.randomUUID();
    }
    const idempotencyKey = idempotencyKeyRef.current;

    try {
      setPhase("creating_intent");
      const { response: intent } = await createUserStoryUpload(
        {
          venueId,
          mediaType: asset.mediaType,
          mimeType: asset.mimeType,
          byteSize: asset.byteSize,
          caption: caption.trim() || null,
          vibeTags: tags,
          attributionMode: attribution,
          replyPolicy,
        },
        { idempotencyKey },
      );

      await savePendingStoryUpload({
        uploadId: intent.upload_id,
        storyId: intent.story_id,
        venueId,
        idempotencyKey,
        updatedAt: new Date().toISOString(),
      });

      if (!intent.upload?.url) {
        // Idempotent replay may already be past PUT — poll status.
        setUploadStatus(intent);
        setPhase(
          mapStoryUploadPhase(
            intent.lifecycle_status,
            intent.publication_status,
            intent.moderation_status,
          ),
        );
        return;
      }

      setPhase("uploading");
      setProgress(0);
      await uploadFileViaFileSystem({
        uploadUrl: intent.upload.url,
        headers: intent.upload.headers,
        fileUri: asset.uri,
        onProgress: setProgress,
      });
      setProgress(null);
      setPhase("completing");
      const completed = await completeUserStoryUpload(intent.upload_id);
      setUploadStatus(completed);
      const mapped = mapStoryUploadPhase(
        completed.lifecycle_status,
        completed.publication_status,
        completed.moderation_status,
      );
      setPhase(mapped);
      if (mapped === "published") {
        await clearPendingStoryUpload();
        onPublished();
      }
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "STORIES_DISABLED") {
          setPhase("unavailable");
          setError("Stories are unavailable right now.");
          return;
        }
        if (
          err.code === "PRESENCE_REQUIRED" ||
          err.code === "PRESENCE_NOT_VERIFIED" ||
          err.code === "PRESENCE_EXPIRED"
        ) {
          setPhase("failed");
          setError("Verified presence is required to post a Story.");
          return;
        }
        if (err.code === "DEVICE_REVOKED") {
          setPhase("failed");
          setError("This device is no longer authorized.");
          return;
        }
      }
      setPhase("failed");
      setError(err instanceof Error ? err.message : "Couldn’t upload Story.");
    }
  };

  const restartExpired = async () => {
    await clearPendingStoryUpload();
    idempotencyKeyRef.current = null;
    setUploadStatus(null);
    setPhase("idle");
    setError(null);
  };

  const busy =
    phase === "creating_intent" ||
    phase === "uploading" ||
    phase === "completing" ||
    phase === "processing" ||
    phase === "moderation_pending";

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={() => {
        if (!busy) {
          onClose();
        }
      }}
      testID="story-composer-modal"
    >
      <View style={[styles.root, { paddingTop: insets.top + 8, paddingBottom: insets.bottom + 12 }]}>
        <View style={styles.header}>
          <Text style={styles.title} accessibilityRole="header">
            New Story
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Cancel Story composer"
            disabled={busy}
            onPress={() => {
              cancelledRef.current = true;
              stopPolling();
              onClose();
            }}
            testID="story-composer-cancel"
          >
            <Text style={styles.cancel}>Cancel</Text>
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          <Text style={styles.venue} testID="story-composer-venue">
            Posting at {venueName}
          </Text>
          <Text style={styles.hint}>Venue is fixed to your verified presence.</Text>

          {asset ? (
            <View style={styles.previewWrap}>
              <Image
                source={{ uri: asset.uri }}
                style={styles.preview}
                contentFit="cover"
                testID="story-composer-preview"
              />
              <Text style={styles.mediaMeta}>
                {asset.mediaType === "video" ? "Video" : "Photo"} ·{" "}
                {Math.round(asset.byteSize / 1024)} KB
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Remove media"
                disabled={busy}
                onPress={() => setAsset(null)}
              >
                <Text style={styles.link}>Remove</Text>
              </Pressable>
            </View>
          ) : (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Choose photo or video"
              style={styles.pickBtn}
              onPress={() => {
                void pickMedia();
              }}
              testID="story-composer-pick"
            >
              <Text style={styles.pickText}>Choose photo or short video</Text>
            </Pressable>
          )}

          <TextInput
            value={caption}
            onChangeText={(t) => setCaption(t.slice(0, 280))}
            placeholder="Caption (optional)"
            placeholderTextColor={colors.textTertiary}
            style={styles.input}
            multiline
            maxLength={280}
            editable={!busy}
            testID="story-composer-caption"
          />

          <Text style={styles.section}>Vibe tags</Text>
          <View style={styles.tagRow}>
            {SUGGESTED_TAGS.map((tag) => {
              const selected = tags.includes(tag);
              return (
                <Pressable
                  key={tag}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  disabled={busy}
                  onPress={() => toggleTag(tag)}
                  style={[styles.tag, selected && styles.tagSelected]}
                >
                  <Text style={[styles.tagText, selected && styles.tagTextSelected]}>
                    #{tag}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          <Text style={styles.section}>Attribution</Text>
          <View style={styles.row}>
            {(
              [
                ["attributed", "With your profile"],
                ["anonymous", "Anonymous"],
              ] as const
            ).map(([mode, label]) => (
              <Pressable
                key={mode}
                accessibilityRole="button"
                accessibilityState={{ selected: attribution === mode }}
                disabled={busy}
                onPress={() => setAttribution(mode)}
                style={[styles.choice, attribution === mode && styles.choiceSelected]}
                testID={`story-composer-attr-${mode}`}
              >
                <Text style={styles.choiceText}>{label}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.section}>Replies</Text>
          <View style={styles.row}>
            {(
              [
                ["disabled", "Off"],
                ["connections", "Connections"],
                ["everyone", "Everyone"],
              ] as const
            ).map(([mode, label]) => (
              <Pressable
                key={mode}
                accessibilityRole="button"
                accessibilityState={{ selected: replyPolicy === mode }}
                disabled={busy}
                onPress={() => setReplyPolicy(mode)}
                style={[styles.choice, replyPolicy === mode && styles.choiceSelected]}
              >
                <Text style={styles.choiceText}>{label}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.status} testID="story-composer-status">
            {phaseLabel(phase, progress)}
          </Text>
          {error ? (
            <Text style={styles.error} testID="story-composer-error">
              {error}
            </Text>
          ) : null}

          {phase === "upload_expired" ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Start a new Story upload"
              onPress={() => {
                void restartExpired();
              }}
              style={styles.primary}
            >
              <Text style={styles.primaryText}>Start over</Text>
            </Pressable>
          ) : (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Submit Story"
              disabled={busy || !asset || phase === "published" || phase === "unavailable"}
              onPress={() => {
                void submit();
              }}
              style={[styles.primary, (busy || !asset) && styles.primaryDisabled]}
              testID="story-composer-submit"
            >
              {busy ? (
                <ActivityIndicator color={colors.neonText} />
              ) : (
                <Text style={styles.primaryText}>
                  {phase === "failed" || phase === "rejected" ? "Retry" : "Share Story"}
                </Text>
              )}
            </Pressable>
          )}
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.backgroundPrimary,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
  },
  cancel: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 14,
  },
  body: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
    gap: spacing.sm,
  },
  venue: {
    color: colors.neon,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 14,
  },
  hint: {
    color: colors.textTertiary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
    marginBottom: spacing.sm,
  },
  pickBtn: {
    minHeight: 120,
    borderRadius: radii.large,
    borderWidth: 1,
    borderColor: colors.borderMedium,
    borderStyle: "dashed",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceElevated,
  },
  pickText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 14,
  },
  previewWrap: {
    gap: 8,
  },
  preview: {
    width: "100%",
    height: 220,
    borderRadius: radii.large,
  },
  mediaMeta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  link: {
    color: colors.gold,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  input: {
    minHeight: 72,
    borderRadius: radii.medium,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    backgroundColor: colors.surfaceSolid,
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    padding: spacing.sm,
    textAlignVertical: "top",
  },
  section: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
    marginTop: spacing.xs,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  tagRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  tag: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  tagSelected: {
    borderColor: colors.neon,
    backgroundColor: colors.surfacePressed,
  },
  tagText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  tagTextSelected: {
    color: colors.neon,
  },
  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  choice: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  choiceSelected: {
    borderColor: colors.neon,
    backgroundColor: colors.surfacePressed,
  },
  choiceText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
  },
  status: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    marginTop: spacing.sm,
  },
  error: {
    color: colors.danger,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  primary: {
    marginTop: spacing.md,
    minHeight: 48,
    borderRadius: radii.pill,
    backgroundColor: colors.neon,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryDisabled: {
    opacity: 0.45,
  },
  primaryText: {
    color: colors.neonText,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 15,
  },
});
