import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Crypto from "expo-crypto";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import {
  completeMediaUpload,
  createMediaUpload,
  fetchUploadStatus,
  fetchVenueVibes,
  type UploadStatus,
} from "@/features/experience/api";
import { LiveVibeCard } from "@/features/experience/LiveVibeCard";
import {
  loadDevFixtureJpeg,
  mapLifecycleToPhase,
  pickImageFromLibrary,
  uploadFileViaFileSystem,
  type SelectedMediaAsset,
  type UploadPhase,
} from "@/features/experience/uploadHelpers";
import { resolveVibeDisplayState } from "@/features/experience/vibeLifecycle";
import {
  composerShouldShow,
  reconcileVibeFeed,
  type FeedListItem,
} from "@/features/experience/vibeMedia";
import { fetchPresenceMe } from "@/features/presence/api";
import {
  fetchExperienceStoryGroups,
  type StoryGroupSummary,
} from "@/features/stories/api";
import { StoryComposerModal } from "@/features/stories/StoryComposerModal";
import { StoryRail } from "@/features/stories/StoryRail";
import { StoryViewerModal } from "@/features/stories/StoryViewerModal";
import { tabScreenBottomPadding } from "@/navigation/tabBar";
import { colors, fontFamilies, radii, spacing } from "@/theme";

const TERMINAL = new Set([
  "ready",
  "invalid",
  "rejected",
  "processing_failed",
  "upload_expired",
  "revoked",
  "deleted",
]);

type FeedFilter = "for_you" | "nearby" | "live_now";

function phaseLabel(phase: UploadPhase): string {
  switch (phase) {
    case "idle":
      return "Ready to share";
    case "picking":
      return "Opening photo library…";
    case "permission_denied":
      return "Photo library permission denied";
    case "cancelled":
      return "Selection cancelled";
    case "creating_intent":
      return "Creating upload…";
    case "uploading":
      return "Uploading…";
    case "completing":
      return "Confirming…";
    case "processing":
      return "Processing…";
    case "published":
      return "Published";
    case "rejected":
      return "Rejected";
    case "failed_retryable":
      return "Couldn’t process";
    case "failed_permanent":
      return "Couldn’t process";
    default:
      return phase;
  }
}

function optimisticStatusForPhase(
  phase: UploadPhase,
): "uploading" | "processing" | "under_review" {
  if (phase === "uploading" || phase === "creating_intent" || phase === "completing") {
    return "uploading";
  }
  if (phase === "processing") {
    return "processing";
  }
  return "under_review";
}

export function ExperienceScreen() {
  const auth = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [viewerGroupKey, setViewerGroupKey] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const bottomPad = tabScreenBottomPadding(insets.bottom);
  const listRef = useRef<FlatList<FeedListItem>>(null);
  const [filter, setFilter] = useState<FeedFilter>("for_you");
  const [uploadStatus, setUploadStatus] = useState<UploadStatus | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [previewUri, setPreviewUri] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [clientRequestId, setClientRequestId] = useState<string | null>(null);
  const [optimisticLiveVibeId, setOptimisticLiveVibeId] = useState<string | null>(null);
  const [successBanner, setSuccessBanner] = useState<string | null>(null);
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  const storiesQuery = useQuery({
    queryKey: ["stories", "experience"],
    queryFn: fetchExperienceStoryGroups,
    enabled: auth.status === "authenticated",
    refetchInterval: 30_000,
    retry: (count, error) => {
      if (error instanceof ApiError && error.code === "STORIES_DISABLED") {
        return false;
      }
      return count < 2;
    },
  });

  const storiesUnavailable =
    storiesQuery.error instanceof ApiError &&
    storiesQuery.error.code === "STORIES_DISABLED";

  const storyGroups =
    auth.status === "authenticated" ? (storiesQuery.data?.items ?? []) : [];

  const applyStoryGroups = (groups: StoryGroupSummary[]) => {
    queryClient.setQueryData(["stories", "experience"], { items: groups });
  };

  const resetComposer = () => {
    setUploadStatus(null);
    setUploadError(null);
    setPhase("idle");
    setUploadProgress(null);
    setPreviewUri(null);
    setCaption("");
    setSelectedTags([]);
    setClientRequestId(null);
    setOptimisticLiveVibeId(null);
  };

  useEffect(() => {
    return () => {
      if (resetTimerRef.current) {
        clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!uploadStatus || TERMINAL.has(uploadStatus.lifecycle_status)) {
      return;
    }
    const timer = setInterval(() => {
      void fetchUploadStatus(uploadStatus.upload_id)
        .then((next) => {
          setUploadStatus(next);
          if (next.live_vibe_id) {
            setOptimisticLiveVibeId(next.live_vibe_id);
          }
          const nextPhase = mapLifecycleToPhase(
            next.lifecycle_status,
            next.moderation_status,
          );
          setPhase(nextPhase);
          if (next.lifecycle_status === "ready") {
            setUploadProgress(null);
            // Refresh Live Vibe surfaces only — never identity/cover media.
            void Promise.all([
              queryClient.invalidateQueries({ queryKey: ["vibes", venueId] }),
              queryClient.invalidateQueries({
                queryKey: ["venue", venueId, "vibes-preview"],
              }),
            ]).then(() => {
              setSuccessBanner("Live Vibe published");
              if (resetTimerRef.current) {
                clearTimeout(resetTimerRef.current);
              }
              resetTimerRef.current = setTimeout(() => {
                setSuccessBanner(null);
                resetComposer();
              }, 1800);
            });
          }
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [uploadStatus, queryClient, venueId]);

  const uploadMutation = useMutation({
    mutationFn: async (asset: SelectedMediaAsset) => {
      const requestId = Crypto.randomUUID();
      setClientRequestId(requestId);
      setOptimisticLiveVibeId(null);
      setUploadError(null);
      setSuccessBanner(null);
      setPhase("creating_intent");
      setPreviewUri(asset.uri);
      setUploadProgress(null);
      const intent = await createMediaUpload({
        venueId: String(venueId),
        mediaType: "image",
        mimeType: asset.mimeType,
        byteSize: asset.byteSize,
        caption: caption.trim() || undefined,
        vibeTags: selectedTags,
      });
      setOptimisticLiveVibeId(intent.live_vibe_id);
      setPhase("uploading");
      setUploadProgress(0);
      await uploadFileViaFileSystem({
        uploadUrl: intent.upload.url,
        headers: intent.upload.headers,
        fileUri: asset.uri,
        onProgress: setUploadProgress,
      });
      setUploadProgress(null);
      setPhase("completing");
      await completeMediaUpload(intent.upload_id);
      const status = await fetchUploadStatus(intent.upload_id);
      setUploadStatus(status);
      if (status.live_vibe_id) {
        setOptimisticLiveVibeId(status.live_vibe_id);
      }
      const nextPhase = mapLifecycleToPhase(status.lifecycle_status, status.moderation_status);
      setPhase(nextPhase);
      if (status.lifecycle_status === "ready") {
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: ["vibes", venueId] }),
          queryClient.invalidateQueries({
            queryKey: ["venue", venueId, "vibes-preview"],
          }),
        ]).then(() => {
          setSuccessBanner("Live Vibe published");
          if (resetTimerRef.current) {
            clearTimeout(resetTimerRef.current);
          }
          resetTimerRef.current = setTimeout(() => {
            setSuccessBanner(null);
            resetComposer();
          }, 1800);
        });
      }
      return status;
    },
    onError: (error: Error) => {
      setPhase("failed_retryable");
      setUploadProgress(null);
      setUploadError(error.message);
    },
  });

  const optimisticRows = useMemo<FeedListItem[]>(() => {
    if (!clientRequestId || !previewUri) {
      return [];
    }
    if (phase === "idle" || phase === "published" || phase === "cancelled") {
      return [];
    }
    if (
      phase === "failed_retryable" ||
      phase === "failed_permanent" ||
      phase === "rejected" ||
      phase === "permission_denied"
    ) {
      return [];
    }
    const now = new Date();
    return [
      {
        kind: "optimistic",
        id: `optimistic:${clientRequestId}`,
        clientRequestId,
        liveVibeId: optimisticLiveVibeId,
        localUri: previewUri,
        caption: caption.trim() || null,
        vibeTags: selectedTags,
        authorLabel: "You",
        publishedAt: now.toISOString(),
        expiresAt: new Date(now.getTime() + 12 * 60 * 60 * 1000).toISOString(),
        status: optimisticStatusForPhase(phase),
      },
    ];
  }, [
    caption,
    clientRequestId,
    optimisticLiveVibeId,
    phase,
    previewUri,
    selectedTags,
  ]);

  const serverItems = useMemo(() => {
    const items = feedQuery.data?.items ?? [];
    return items.filter((item) => {
      const state = resolveVibeDisplayState({
        publishedAt: item.published_at,
        expiresAt: item.expires_at,
      });
      if (filter === "live_now") {
        return state === "LIVE";
      }
      return state !== "ARCHIVED";
    });
  }, [feedQuery.data?.items, filter]);

  const feedRows = useMemo(
    () => reconcileVibeFeed({ serverItems, optimistic: optimisticRows }),
    [optimisticRows, serverItems],
  );

  const showComposerChrome =
    canPost &&
    !successBanner &&
    phase !== "idle" &&
    phase !== "published" &&
    phase !== "cancelled" &&
    (composerShouldShow(phase) ||
      Boolean(uploadError) ||
      Boolean(previewUri) ||
      phase === "failed_retryable" ||
      phase === "failed_permanent" ||
      phase === "rejected" ||
      phase === "permission_denied");

  const showUploadPercent = phase === "uploading" && uploadProgress != null;

  const listHeader = (
    <View testID="experience-list-header">
      <View style={styles.header}>
        <Text style={styles.title} accessibilityRole="header">
          Experience
        </Text>
        <Text style={styles.support}>See the night as it happens.</Text>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.filters}
        testID="experience-filters"
      >
        {(
          [
            ["for_you", "For You"],
            ["nearby", "Nearby"],
            ["live_now", "Live Now"],
          ] as const
        ).map(([key, label]) => (
          <Pressable
            key={key}
            accessibilityRole="button"
            accessibilityState={{ selected: filter === key }}
            onPress={() => setFilter(key)}
            style={[styles.pill, filter === key && styles.pillActive]}
          >
            <Text style={[styles.pillText, filter === key && styles.pillTextActive]}>
              {label}
            </Text>
          </Pressable>
        ))}
      </ScrollView>

      <View testID="experience-story-row">
        <StoryRail
          groups={storyGroups}
          loading={storiesQuery.isLoading || storiesQuery.isFetching}
          errorMessage={
            storiesUnavailable
              ? null
              : storiesQuery.isError
                ? "Couldn’t load Stories."
                : null
          }
          canCreate={canPost}
          venueName={venueName}
          storiesUnavailable={storiesUnavailable}
          onRetry={() => {
            void storiesQuery.refetch();
          }}
          onPressYourStory={() => {
            if (!canPost || !venueId || !venueName) {
              Alert.alert(
                "Verified presence required",
                "Stories can only be posted while you’re verified at a venue.",
                [
                  { text: "Not now", style: "cancel" },
                  {
                    text: "Go to Presence",
                    onPress: () => router.push("/(tabs)/presence"),
                  },
                ],
              );
              return;
            }
            setComposerOpen(true);
          }}
          onPressGroup={(group) => setViewerGroupKey(group.group_key)}
        />
      </View>

      {canPost ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Share a Live Vibe"
          testID="experience-your-story"
          disabled={uploadMutation.isPending}
          onPress={() => {
            void (async () => {
              setPhase("picking");
              const picked = await pickImageFromLibrary();
              if (picked.status === "cancelled") {
                setPhase("cancelled");
                return;
              }
              if (picked.status === "permission_denied") {
                setPhase("permission_denied");
                return;
              }
              if (picked.status === "invalid") {
                setPhase("failed_permanent");
                setUploadError(picked.message);
                return;
              }
              uploadMutation.mutate(picked.asset);
            })();
          }}
          style={styles.liveVibeCta}
        >
          <Text style={styles.liveVibeCtaText}>Share Live Vibe</Text>
          {venueName ? (
            <Text style={styles.liveVibeCtaMeta}>at {venueName}</Text>
          ) : null}
        </Pressable>
      ) : (
        <View style={styles.empty}>
          <Text style={styles.emptyTitle}>Verify your presence first</Text>
          <Text style={styles.emptyBody}>
            Share Live Vibes and Stories while verified at a venue.
          </Text>
        </View>
      )}

      {successBanner ? (
        <View style={styles.successBanner} testID="experience-publish-success">
          <Text style={styles.successText}>{successBanner}</Text>
        </View>
      ) : null}

      {showComposerChrome ? (
        <View style={styles.composerStatus} testID="experience-composer-status">
          <Text style={styles.composerMeta}>
            Sharing to {venueName} · {phaseLabel(phase)}
            {showUploadPercent ? ` · ${Math.round((uploadProgress ?? 0) * 100)}%` : ""}
          </Text>
          {previewUri ? (
            <Image
              source={{ uri: previewUri }}
              style={styles.preview}
              contentFit="cover"
              testID="experience-composer-preview"
            />
          ) : null}
          {uploadError ? <Text style={styles.error}>{uploadError}</Text> : null}
          {__DEV__ ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Use development fixture image"
              testID="experience-dev-fixture"
              onPress={() => {
                void loadDevFixtureJpeg().then((asset) => uploadMutation.mutate(asset));
              }}
            >
              <Text style={styles.devLink}>Use fixture image</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {feedQuery.isLoading ? (
        <ActivityIndicator color={colors.lime} style={styles.loader} />
      ) : null}
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="experience-screen">
      <FlatList
        ref={listRef}
        style={styles.list}
        data={feedRows}
        keyExtractor={(item) => item.id}
        ListHeaderComponent={listHeader}
        contentContainerStyle={[styles.feed, { paddingBottom: bottomPad }]}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        ListEmptyComponent={
          !feedQuery.isLoading && canPost ? (
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>The night hasn’t started yet</Text>
              <Text style={styles.emptyBody}>
                Live Vibes from nearby venues will appear here once people share.
              </Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => (
          <LiveVibeCard
            row={item}
            onRetryMedia={() => {
              void feedQuery.refetch();
            }}
          />
        )}
      />

      <StoryViewerModal
        visible={auth.status === "authenticated" && Boolean(viewerGroupKey)}
        groups={storyGroups}
        initialGroupKey={viewerGroupKey}
        onClose={() => setViewerGroupKey(null)}
        onGroupsChange={applyStoryGroups}
        onDeleted={() => {
          void queryClient.invalidateQueries({ queryKey: ["stories"] });
        }}
      />

      {venueId && venueName ? (
        <StoryComposerModal
          visible={composerOpen && auth.status === "authenticated"}
          venueId={venueId}
          venueName={venueName}
          sessionActive={auth.status === "authenticated"}
          onClose={() => setComposerOpen(false)}
          onPublished={() => {
            setComposerOpen(false);
            void queryClient.invalidateQueries({ queryKey: ["stories"] });
          }}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.backgroundPrimary },
  list: { flex: 1 },
  header: { paddingHorizontal: spacing.lg, paddingTop: spacing.xs, gap: 4 },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 36,
  },
  support: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
  },
  filters: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    gap: spacing.xs,
  },
  pill: {
    minHeight: 36,
    paddingHorizontal: 14,
    borderRadius: radii.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderSubtle,
    backgroundColor: colors.surfaceSolid,
    alignItems: "center",
    justifyContent: "center",
  },
  pillActive: { backgroundColor: colors.neon, borderColor: colors.neon },
  pillText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 12,
  },
  pillTextActive: { color: colors.neonText },
  storyRow: {
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
    paddingBottom: spacing.sm,
  },
  storyItem: { width: 72, alignItems: "center", gap: 6 },
  storyRing: {
    width: 64,
    height: 64,
    borderRadius: 32,
    borderWidth: 2,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceElevated,
  },
  storyRingYours: { borderColor: colors.neon },
  storyRingVenue: { borderColor: colors.gold },
  plus: {
    color: colors.neon,
    fontFamily: fontFamilies.geistBold,
    fontSize: 28,
    marginTop: -2,
  },
  storyInitial: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 22,
  },
  storyLabel: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 10,
    textAlign: "center",
  },
  composerStatus: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    gap: 8,
  },
  composerMeta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  preview: { width: 96, height: 96, borderRadius: radii.medium },
  error: { color: colors.danger, fontFamily: fontFamilies.geistRegular, fontSize: 12 },
  devLink: { color: colors.gold, fontFamily: fontFamilies.geistMedium, fontSize: 12 },
  successBanner: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    minHeight: 40,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "rgba(185,249,8,0.35)",
    backgroundColor: "rgba(185,249,8,0.08)",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 12,
  },
  successText: {
    color: colors.neon,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 13,
  },
  liveVibeCta: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: radii.medium,
    borderWidth: 1,
    borderColor: colors.borderMedium,
    backgroundColor: colors.surfaceElevated,
    gap: 2,
  },
  liveVibeCtaText: {
    color: colors.neon,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 13,
  },
  liveVibeCtaMeta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  loader: { marginVertical: spacing.md },
  feed: {
    paddingHorizontal: spacing.lg,
    flexGrow: 1,
  },
  separator: { height: 14 },
  empty: { paddingVertical: spacing.lg, gap: spacing.xs },
  emptyTitle: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 26,
  },
  emptyBody: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    lineHeight: 20,
  },
});
