import { useEventListener } from "expo";
import { Image } from "expo-image";
import { useVideoPlayer, VideoView } from "expo-video";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import {
  computeVideoProgressFraction,
  decideVideoPlayback,
  shouldAdvanceAfterVideoComplete,
} from "@/features/stories/storyVideoPlayback";
import { colors, fontFamilies, radii, spacing } from "@/theme";

type Props = {
  videoUri: string;
  posterUri: string | null;
  active: boolean;
  paused: boolean;
  onProgress: (fraction: number) => void;
  onPlaybackComplete: () => void;
  onPlaybackStarted: () => void;
  onError: () => void;
};

/**
 * Active-slide-only Story video player.
 * Unmount when the slide is inactive so other videos are never preloaded/played.
 */
export function StoryVideoSlide({
  videoUri,
  posterUri,
  active,
  paused,
  onProgress,
  onPlaybackComplete,
  onPlaybackStarted,
  onError,
}: Props) {
  const [showPoster, setShowPoster] = useState(true);
  const [status, setStatus] = useState<string>("idle");
  const [failed, setFailed] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const startedRef = useRef(false);
  const completedRef = useRef(false);
  const source = `${videoUri}#r=${retryToken}`;

  const player = useVideoPlayer(source, (instance) => {
    instance.loop = false;
    instance.timeUpdateEventInterval = 0.05;
    instance.staysActiveInBackground = false;
    instance.showNowPlayingNotification = false;
  });

  // Reset bookkeeping when the source identity changes (new URI or retry remount).
  useEffect(() => {
    startedRef.current = false;
    completedRef.current = false;
  }, [source]);

  useEffect(() => {
    const decision = decideVideoPlayback({
      active,
      paused,
      hasSource: Boolean(videoUri),
      status,
    });
    if (decision.shouldPlay) {
      player.play();
    } else {
      player.pause();
    }
  }, [active, paused, videoUri, status, player]);

  useEffect(() => {
    return () => {
      try {
        player.pause();
      } catch {
        // Player may already be released on unmount.
      }
    };
  }, [player]);

  useEventListener(player, "statusChange", ({ status: next }) => {
    setStatus(next);
    if (next === "error") {
      setFailed(true);
      onError();
    }
  });

  useEventListener(player, "playingChange", ({ isPlaying }) => {
    if (isPlaying && active && !startedRef.current) {
      startedRef.current = true;
      onPlaybackStarted();
    }
  });

  useEventListener(player, "timeUpdate", ({ currentTime }) => {
    if (!active || paused || status === "loading") {
      return;
    }
    const fraction = computeVideoProgressFraction(currentTime, player.duration);
    if (fraction == null) {
      return;
    }
    onProgress(fraction);
  });

  useEventListener(player, "playToEnd", () => {
    if (completedRef.current) {
      return;
    }
    if (
      !shouldAdvanceAfterVideoComplete({
        active,
        buffering: status === "loading",
      })
    ) {
      return;
    }
    completedRef.current = true;
    onProgress(1);
    onPlaybackComplete();
  });

  return (
    <View style={styles.wrap} testID="story-video-slide">
      <VideoView
        player={player}
        style={styles.video}
        contentFit="contain"
        nativeControls={false}
        onFirstFrameRender={() => {
          setShowPoster(false);
          setFailed(false);
        }}
        accessibilityLabel={
          paused || !active ? "Story video paused" : "Story video playing"
        }
      />

      {showPoster && posterUri ? (
        <Image
          source={{ uri: posterUri }}
          style={styles.poster}
          contentFit="contain"
          accessibilityLabel="Story video poster"
          testID="story-video-poster"
        />
      ) : null}

      {active && !failed && (status === "loading" || showPoster) ? (
        <ActivityIndicator color={colors.neon} style={styles.spinner} />
      ) : null}

      {failed ? (
        <View style={styles.errorBox} testID="story-video-error">
          <Text style={styles.errorText}>Couldn’t play this video.</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Retry video playback"
            onPress={() => {
              setFailed(false);
              setShowPoster(true);
              setRetryToken((n) => n + 1);
            }}
            style={styles.retry}
            testID="story-video-retry"
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : null}

      <Text
        style={styles.stateHint}
        accessibilityLiveRegion="polite"
        accessibilityLabel={paused || !active ? "Paused" : "Playing"}
      >
        {paused || !active ? "Paused" : "Playing"}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    justifyContent: "center",
  },
  video: {
    width: "100%",
    height: "100%",
  },
  poster: {
    ...StyleSheet.absoluteFill,
  },
  spinner: {
    position: "absolute",
    alignSelf: "center",
  },
  errorBox: {
    ...StyleSheet.absoluteFill,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    backgroundColor: "rgba(0,0,0,0.55)",
    padding: spacing.lg,
  },
  errorText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    textAlign: "center",
  },
  retry: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.neon,
  },
  retryText: {
    color: colors.neon,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  stateHint: {
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
    fontFamily: fontFamilies.geistMedium,
  },
});
