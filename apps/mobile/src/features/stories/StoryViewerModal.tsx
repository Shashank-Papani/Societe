import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Image } from "expo-image";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError } from "@/api/client";
import {
  deleteStory,
  fetchStoryGroup,
  recordStoryView,
  reportStory,
  STORY_REPORT_REASONS,
  type StoryGroupDetail,
  type StoryGroupSummary,
  type StoryReportReason,
  type StorySlide,
} from "@/features/stories/api";
import {
  applyOptimisticView,
  formatRelativeExpiry,
  IMAGE_SLIDE_DURATION_MS,
  pickStoryDisplayVariant,
  pickStoryPosterVariant,
  pickStoryVideoVariant,
  removeStoryFromDetail,
  shouldRecordView,
  VIEW_RECORD_DELAY_MS,
} from "@/features/stories/storyHelpers";
import { StoryVideoSlide } from "@/features/stories/StoryVideoSlide";
import {
  canRefreshSignedMediaUrl,
  markSignedMediaUrlRetry,
} from "@/features/stories/storyVideoPlayback";
import { colors, fontFamilies, radii, spacing } from "@/theme";

type Props = {
  visible: boolean;
  groups: StoryGroupSummary[];
  initialGroupKey: string | null;
  onClose: () => void;
  onGroupsChange: (groups: StoryGroupSummary[]) => void;
  onDeleted: () => void;
};

export function StoryViewerModal({
  visible,
  groups,
  initialGroupKey,
  onClose,
  onGroupsChange,
  onDeleted,
}: Props) {
  const insets = useSafeAreaInsets();
  const [groupKey, setGroupKey] = useState<string | null>(initialGroupKey);
  const [detail, setDetail] = useState<StoryGroupDetail | null>(null);
  const [slideIndex, setSlideIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [holdPaused, setHoldPaused] = useState(false);
  const [appInactive, setAppInactive] = useState(false);
  const [playbackStarted, setPlaybackStarted] = useState(false);
  const [progress, setProgress] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState<StoryReportReason>("spam");
  const [reportDescription, setReportDescription] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const recordedRef = useRef<Set<string>>(new Set());
  const visibleSinceRef = useRef<number>(0);
  const urlRetryRef = useRef<Set<string>>(new Set());
  const progressTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const viewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const slides = detail?.slides ?? [];
  const slide: StorySlide | null = slides[slideIndex] ?? null;
  const paused = holdPaused || appInactive || menuOpen || reportOpen;
  const groupOrder = useMemo(() => groups.map((g) => g.group_key), [groups]);

  const clearTimers = useCallback(() => {
    if (progressTimerRef.current) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
    if (viewTimerRef.current) {
      clearTimeout(viewTimerRef.current);
      viewTimerRef.current = null;
    }
  }, []);

  const loadGroup = useCallback(async (key: string, preserveIndex = false) => {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchStoryGroup(key);
      setDetail(next);
      setGroupKey(key);
      if (!preserveIndex) {
        setSlideIndex(0);
      } else {
        setSlideIndex((idx) => Math.min(idx, Math.max(0, next.slides.length - 1)));
      }
      setProgress(0);
      visibleSinceRef.current = Date.now();
    } catch (err) {
      const code = err instanceof ApiError ? err.code : null;
      if (code === "STORY_NOT_FOUND" || code === "STORY_EXPIRED") {
        setError("This Story is no longer available.");
        setDetail(null);
      } else if (code === "STORIES_DISABLED") {
        setError("Stories are unavailable.");
      } else {
        setError(err instanceof Error ? err.message : "Couldn’t open this Story.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!visible || !initialGroupKey) {
      return;
    }
    recordedRef.current = new Set();
    urlRetryRef.current = new Set();
    // Modal open is an external UI event — load slides for the opaque group key.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional modal fetch on open
    void loadGroup(initialGroupKey);
  }, [visible, initialGroupKey, loadGroup]);

  useEffect(() => {
    if (visible) {
      return;
    }
    clearTimers();
    // Reset transient viewer UI when the modal is dismissed.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional modal teardown
    setDetail(null);
    setMenuOpen(false);
    setReportOpen(false);
    setHoldPaused(false);
    setAppInactive(false);
    setPlaybackStarted(false);
    setProgress(0);
    setActionError(null);
  }, [visible, clearTimers]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    const sub = AppState.addEventListener("change", (next) => {
      setAppInactive(next !== "active");
    });
    return () => sub.remove();
  }, [visible]);

  const goNextGroupOrClose = useCallback(() => {
    if (!groupKey) {
      onClose();
      return;
    }
    const idx = groupOrder.indexOf(groupKey);
    const nextKey = idx >= 0 ? groupOrder[idx + 1] : undefined;
    if (nextKey) {
      void loadGroup(nextKey);
      return;
    }
    onClose();
  }, [groupKey, groupOrder, loadGroup, onClose]);

  const goNextSlide = useCallback(() => {
    if (!detail) {
      return;
    }
    if (slideIndex < detail.slides.length - 1) {
      setSlideIndex((i) => i + 1);
      setProgress(0);
      setPlaybackStarted(false);
      visibleSinceRef.current = Date.now();
      return;
    }
    goNextGroupOrClose();
  }, [detail, slideIndex, goNextGroupOrClose]);

  const goPrevSlide = useCallback(() => {
    if (slideIndex > 0) {
      setSlideIndex((i) => i - 1);
      setProgress(0);
      setPlaybackStarted(false);
      visibleSinceRef.current = Date.now();
      return;
    }
    if (!groupKey) {
      return;
    }
    const idx = groupOrder.indexOf(groupKey);
    const prevKey = idx > 0 ? groupOrder[idx - 1] : undefined;
    if (prevKey) {
      void loadGroup(prevKey).then(() => undefined);
    }
  }, [slideIndex, groupKey, groupOrder, loadGroup]);

  const recordViewIfNeeded = useCallback(
    (storyId: string, mediaType: "image" | "video", startedPlayback: boolean) => {
      if (recordedRef.current.has(storyId)) {
        return;
      }
      const visibleMs = Date.now() - visibleSinceRef.current;
      if (
        !shouldRecordView({
          visibleMs,
          mediaType,
          alreadyRecorded: false,
          playbackStarted: startedPlayback,
        })
      ) {
        return;
      }
      recordedRef.current.add(storyId);
      void recordStoryView(storyId)
        .then(() => {
          if (groupKey) {
            onGroupsChange(applyOptimisticView(groups, storyId, groupKey));
          }
        })
        .catch(() => {
          recordedRef.current.delete(storyId);
        });
    },
    [groupKey, groups, onGroupsChange],
  );

  // Image slides: timed progress + view after visible threshold.
  useEffect(() => {
    clearTimers();
    if (
      !visible ||
      !slide ||
      slide.media_type !== "image" ||
      paused ||
      loading
    ) {
      return;
    }
    const started = Date.now();
    if (visibleSinceRef.current <= 0) {
      visibleSinceRef.current = started;
    }
    progressTimerRef.current = setInterval(() => {
      const fraction = Math.min(1, (Date.now() - started) / IMAGE_SLIDE_DURATION_MS);
      setProgress(fraction);
      if (fraction >= 1) {
        clearTimers();
        goNextSlide();
      }
    }, 50);

    const storyId = slide.story_id;
    if (!recordedRef.current.has(storyId)) {
      viewTimerRef.current = setTimeout(() => {
        recordViewIfNeeded(storyId, "image", false);
      }, VIEW_RECORD_DELAY_MS);
    }

    return clearTimers;
  }, [
    visible,
    slide,
    paused,
    loading,
    clearTimers,
    goNextSlide,
    recordViewIfNeeded,
  ]);

  // Video slides: view only after genuine playback has started.
  useEffect(() => {
    if (
      !visible ||
      !slide ||
      slide.media_type !== "video" ||
      !playbackStarted ||
      paused ||
      loading
    ) {
      return;
    }
    const storyId = slide.story_id;
    if (recordedRef.current.has(storyId)) {
      return;
    }
    const startedAt = Date.now();
    visibleSinceRef.current = startedAt;
    viewTimerRef.current = setTimeout(() => {
      recordViewIfNeeded(storyId, "video", true);
    }, VIEW_RECORD_DELAY_MS);
    return () => {
      if (viewTimerRef.current) {
        clearTimeout(viewTimerRef.current);
        viewTimerRef.current = null;
      }
    };
  }, [visible, slide, playbackStarted, paused, loading, recordViewIfNeeded]);

  const imageVariant =
    slide && slide.media_type === "image"
      ? pickStoryDisplayVariant(slide.variants, "image")
      : null;
  const videoVariant =
    slide && slide.media_type === "video" ? pickStoryVideoVariant(slide.variants) : null;
  const posterVariant =
    slide && slide.media_type === "video" ? pickStoryPosterVariant(slide.variants) : null;

  const onMediaError = async () => {
    if (!groupKey || !slide) {
      return;
    }
    if (!canRefreshSignedMediaUrl({ storyId: slide.story_id, alreadyRetried: urlRetryRef.current })) {
      return;
    }
    urlRetryRef.current = markSignedMediaUrlRetry(urlRetryRef.current, slide.story_id);
    await loadGroup(groupKey, true);
  };

  const submitReport = async () => {
    if (!slide) {
      return;
    }
    setActionBusy(true);
    setActionError(null);
    try {
      await reportStory(slide.story_id, {
        reason: reportReason,
        description: reportDescription.trim() || null,
      });
      setReportOpen(false);
      setMenuOpen(false);
      Alert.alert("Report submitted", "Thanks — our team will review this Story.");
    } catch (err) {
      if (err instanceof ApiError && err.code === "STORY_REPORT_DUPLICATE") {
        setActionError("You already reported this Story.");
      } else {
        setActionError(err instanceof Error ? err.message : "Couldn’t submit report.");
      }
    } finally {
      setActionBusy(false);
    }
  };

  const confirmDelete = () => {
    if (!slide || !detail) {
      return;
    }
    Alert.alert("Delete Story?", "This removes the Story for everyone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: () => {
          void (async () => {
            setActionBusy(true);
            setActionError(null);
            try {
              await deleteStory(slide.story_id);
              const next = removeStoryFromDetail(detail, slide.story_id);
              onDeleted();
              if (next.empty) {
                onClose();
                return;
              }
              setDetail({ ...detail, slides: next.slides });
              setSlideIndex((i) => Math.min(i, next.slides.length - 1));
              setMenuOpen(false);
            } catch (err) {
              setActionError(err instanceof Error ? err.message : "Couldn’t delete Story.");
            } finally {
              setActionBusy(false);
            }
          })();
        },
      },
    ]);
  };

  return (
    <Modal
      visible={visible}
      animationType="fade"
      presentationStyle="fullScreen"
      onRequestClose={onClose}
      testID="story-viewer-modal"
    >
      <View style={[styles.root, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
        {loading && !detail ? (
          <ActivityIndicator color={colors.neon} style={styles.centerSpinner} />
        ) : null}

        {error && !detail ? (
          <View style={styles.errorWrap} testID="story-viewer-error">
            <Text style={styles.errorText}>{error}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Close Story" onPress={onClose}>
              <Text style={styles.closeText}>Close</Text>
            </Pressable>
          </View>
        ) : null}

        {detail && slide ? (
          <>
            <View style={styles.progressRow} testID="story-viewer-progress">
              {slides.map((s, index) => (
                <View key={s.story_id} style={styles.progressTrack}>
                  <View
                    style={[
                      styles.progressFill,
                      {
                        width:
                          index < slideIndex
                            ? "100%"
                            : index === slideIndex
                              ? `${Math.round(progress * 100)}%`
                              : "0%",
                      },
                    ]}
                  />
                </View>
              ))}
            </View>

            <View style={styles.topBar}>
              <View style={styles.identity}>
                <Text style={styles.author} numberOfLines={1}>
                  {slide.author_label}
                </Text>
                {slide.is_official ? (
                  <Text style={styles.official}>Official</Text>
                ) : null}
                <Text style={styles.meta}>{formatRelativeExpiry(slide.expires_at)}</Text>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Story actions"
                onPress={() => setMenuOpen(true)}
                style={styles.menuBtn}
                testID="story-viewer-menu"
              >
                <Text style={styles.menuDots}>•••</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Close Story viewer"
                onPress={onClose}
                style={styles.closeBtn}
                testID="story-viewer-close"
              >
                <Text style={styles.closeText}>✕</Text>
              </Pressable>
            </View>

            <View style={styles.mediaWrap}>
              {slide.media_type === "video" && videoVariant ? (
                <StoryVideoSlide
                  key={`${slide.story_id}:${videoVariant.url}`}
                  videoUri={videoVariant.url}
                  posterUri={posterVariant?.url ?? null}
                  active={visible && !loading}
                  paused={paused}
                  onProgress={setProgress}
                  onPlaybackComplete={goNextSlide}
                  onPlaybackStarted={() => {
                    setPlaybackStarted(true);
                    visibleSinceRef.current = Date.now();
                  }}
                  onError={() => {
                    void onMediaError();
                  }}
                />
              ) : imageVariant ? (
                <Image
                  source={{ uri: imageVariant.url }}
                  style={styles.media}
                  contentFit="contain"
                  onError={() => {
                    void onMediaError();
                  }}
                  testID="story-viewer-media"
                />
              ) : (
                <Text style={styles.missingMedia}>Media unavailable</Text>
              )}
            </View>

            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Previous Story slide"
              style={styles.tapLeft}
              onPress={goPrevSlide}
              onLongPress={() => setHoldPaused(true)}
              onPressOut={() => setHoldPaused(false)}
              delayLongPress={150}
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Next Story slide"
              style={styles.tapRight}
              onPress={goNextSlide}
              onLongPress={() => setHoldPaused(true)}
              onPressOut={() => setHoldPaused(false)}
              delayLongPress={150}
            />

            <View style={styles.captionWrap} pointerEvents="none">
              {slide.venue ? (
                <Text style={styles.venue}>{slide.venue.name}</Text>
              ) : null}
              {slide.caption ? <Text style={styles.caption}>{slide.caption}</Text> : null}
              {slide.vibe_tags.length > 0 ? (
                <Text style={styles.tags}>{slide.vibe_tags.map((t) => `#${t}`).join(" ")}</Text>
              ) : null}
            </View>
          </>
        ) : null}

        <Modal visible={menuOpen} transparent animationType="fade" onRequestClose={() => setMenuOpen(false)}>
          <Pressable style={styles.sheetBackdrop} onPress={() => setMenuOpen(false)}>
            <View style={styles.sheet} testID="story-action-sheet">
              {slide?.can_report ? (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Report Story"
                  style={styles.sheetItem}
                  onPress={() => {
                    setMenuOpen(false);
                    setReportOpen(true);
                  }}
                >
                  <Text style={styles.sheetDanger}>Report</Text>
                </Pressable>
              ) : null}
              {slide?.can_delete ? (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Delete Story"
                  style={styles.sheetItem}
                  onPress={confirmDelete}
                  disabled={actionBusy}
                >
                  <Text style={styles.sheetDanger}>Delete</Text>
                </Pressable>
              ) : null}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Close menu"
                style={styles.sheetItem}
                onPress={() => setMenuOpen(false)}
              >
                <Text style={styles.sheetText}>Close</Text>
              </Pressable>
              {actionError ? <Text style={styles.actionError}>{actionError}</Text> : null}
            </View>
          </Pressable>
        </Modal>

        <Modal visible={reportOpen} transparent animationType="slide" onRequestClose={() => setReportOpen(false)}>
          <View style={styles.reportSheet} testID="story-report-sheet">
            <Text style={styles.reportTitle}>Report Story</Text>
            {STORY_REPORT_REASONS.map((reason) => (
              <Pressable
                key={reason}
                accessibilityRole="button"
                accessibilityState={{ selected: reportReason === reason }}
                onPress={() => setReportReason(reason)}
                style={[styles.reasonRow, reportReason === reason && styles.reasonSelected]}
              >
                <Text style={styles.sheetText}>{reason.replaceAll("_", " ")}</Text>
              </Pressable>
            ))}
            <TextInput
              value={reportDescription}
              onChangeText={(text) => setReportDescription(text.slice(0, 500))}
              placeholder="Optional details"
              placeholderTextColor={colors.textSecondary}
              style={styles.reportInput}
              multiline
              maxLength={500}
            />
            {actionError ? <Text style={styles.actionError}>{actionError}</Text> : null}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Submit report"
              style={styles.submitReport}
              disabled={actionBusy}
              onPress={() => {
                void submitReport();
              }}
            >
              <Text style={styles.submitReportText}>{actionBusy ? "Submitting…" : "Submit"}</Text>
            </Pressable>
            <Pressable accessibilityRole="button" onPress={() => setReportOpen(false)}>
              <Text style={styles.closeText}>Cancel</Text>
            </Pressable>
          </View>
        </Modal>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#000",
  },
  centerSpinner: {
    marginTop: 80,
  },
  errorWrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    padding: spacing.lg,
  },
  errorText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    textAlign: "center",
  },
  progressRow: {
    flexDirection: "row",
    gap: 4,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
  },
  progressTrack: {
    flex: 1,
    height: 2,
    borderRadius: 1,
    backgroundColor: "rgba(255,255,255,0.25)",
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    backgroundColor: colors.neon,
  },
  topBar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  identity: {
    flex: 1,
    gap: 2,
  },
  author: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 15,
  },
  official: {
    color: colors.neon,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 11,
    textTransform: "uppercase",
  },
  meta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 11,
  },
  menuBtn: {
    padding: 8,
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  menuDots: {
    color: colors.textPrimary,
    fontSize: 18,
  },
  closeBtn: {
    padding: 8,
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  closeText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 16,
  },
  mediaWrap: {
    flex: 1,
    justifyContent: "center",
  },
  media: {
    width: "100%",
    height: "100%",
  },
  missingMedia: {
    color: colors.textSecondary,
    textAlign: "center",
  },
  videoHint: {
    position: "absolute",
    top: spacing.md,
    right: spacing.md,
    color: colors.textPrimary,
    backgroundColor: "rgba(0,0,0,0.5)",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radii.small,
    overflow: "hidden",
    fontSize: 11,
  },
  tapLeft: {
    position: "absolute",
    left: 0,
    top: 120,
    bottom: 120,
    width: "35%",
  },
  tapRight: {
    position: "absolute",
    right: 0,
    top: 120,
    bottom: 120,
    width: "65%",
  },
  captionWrap: {
    position: "absolute",
    left: spacing.lg,
    right: spacing.lg,
    bottom: Platform.OS === "ios" ? 48 : 36,
    gap: 4,
  },
  venue: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  caption: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
  },
  tags: {
    color: colors.neon,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  sheetBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: colors.surfaceElevated,
    borderTopLeftRadius: radii.large,
    borderTopRightRadius: radii.large,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  sheetItem: {
    paddingVertical: 14,
    minHeight: 44,
  },
  sheetText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 16,
  },
  sheetDanger: {
    color: colors.danger,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 16,
  },
  actionError: {
    color: colors.danger,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  reportSheet: {
    flex: 1,
    backgroundColor: colors.backgroundPrimary,
    padding: spacing.lg,
    paddingTop: 64,
    gap: spacing.sm,
  },
  reportTitle: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
    marginBottom: spacing.md,
  },
  reasonRow: {
    paddingVertical: 12,
    paddingHorizontal: spacing.md,
    borderRadius: radii.medium,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  reasonSelected: {
    borderColor: colors.neon,
  },
  reportInput: {
    minHeight: 90,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radii.medium,
    padding: spacing.md,
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    textAlignVertical: "top",
  },
  submitReport: {
    backgroundColor: colors.neon,
    borderRadius: radii.pill,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: spacing.md,
  },
  submitReportText: {
    color: colors.backgroundPrimary,
    fontFamily: fontFamilies.geistMedium,
  },
});
