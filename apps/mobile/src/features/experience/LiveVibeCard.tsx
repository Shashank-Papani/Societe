import { Image } from "expo-image";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { VibeFeedItem } from "@/features/experience/api";
import {
  formatVibeTagLabel,
  resolveVibeDisplayState,
  vibeDisplayLabel,
} from "@/features/experience/vibeLifecycle";
import {
  LIVE_VIBE_MEDIA_ASPECT_RATIO,
  resolveVibeMediaSource,
  type FeedListItem,
} from "@/features/experience/vibeMedia";
import { colors, fontFamilies, radii, spacing } from "@/theme";

type Props = {
  row: FeedListItem;
  onRetryMedia?: () => void;
};

function MediaFrame({
  uri,
  accessibilityLabel,
  onRetry,
}: {
  uri: string | null;
  accessibilityLabel: string;
  onRetry?: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const [nonce, setNonce] = useState(0);

  if (!uri || failed) {
    return (
      <View
        style={styles.mediaFrame}
        accessibilityRole="image"
        accessibilityLabel="Couldn’t load this vibe"
        testID="live-vibe-media-fallback"
      >
        <Text style={styles.fallbackTitle}>Couldn’t load this vibe</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Try again"
          testID="live-vibe-media-retry"
          onPress={() => {
            setFailed(false);
            setNonce((value) => value + 1);
            onRetry?.();
          }}
          style={styles.fallbackButton}
        >
          <Text style={styles.fallbackButtonText}>Try Again</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <Image
      key={`${uri}:${nonce}`}
      source={{ uri }}
      style={styles.mediaFrame}
      contentFit="cover"
      accessibilityLabel={accessibilityLabel}
      testID="live-vibe-media"
      onError={() => setFailed(true)}
    />
  );
}

export function LiveVibeCard({ row, onRetryMedia }: Props) {
  if (row.kind === "optimistic") {
    const resolved = resolveVibeMediaSource({
      variants: [],
      localUri: row.localUri,
      pending: true,
    });
    const statusLabel =
      row.status === "uploading"
        ? "Uploading…"
        : row.status === "under_review"
          ? "Under review"
          : "Processing…";
    return (
      <View style={styles.card} testID={`live-vibe-optimistic-${row.clientRequestId}`}>
        <View style={styles.cardHeader}>
          <View style={styles.cardHeaderCopy}>
            <Text style={styles.author} numberOfLines={1}>
              {row.authorLabel}
            </Text>
            <Text style={styles.meta} numberOfLines={1}>
              {statusLabel}
            </Text>
          </View>
          <View style={styles.recentBadge}>
            <Text style={styles.recentBadgeText}>PENDING</Text>
          </View>
        </View>
        <MediaFrame
          uri={resolved.kind === "local" ? resolved.uri : null}
          accessibilityLabel="Live vibe upload preview"
        />
        {row.caption ? <Text style={styles.caption}>{row.caption}</Text> : null}
      </View>
    );
  }

  const item: VibeFeedItem = row.item;
  const state = resolveVibeDisplayState({
    publishedAt: item.published_at,
    expiresAt: item.expires_at,
  });
  if (state === "ARCHIVED") {
    return null;
  }

  const resolved = resolveVibeMediaSource({
    variants: item.variants,
    localUri: null,
    pending: false,
  });
  const mediaUri = resolved.kind === "remote" ? resolved.uri : null;

  return (
    <View style={styles.card} testID={`live-vibe-${item.id}`}>
      <View style={styles.cardHeader}>
        <View style={styles.cardHeaderCopy}>
          <Text style={styles.author} numberOfLines={1}>
            {item.author_label}
          </Text>
          <Text style={styles.meta} numberOfLines={1}>
            {new Date(item.published_at).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
            })}
          </Text>
        </View>
        {state === "LIVE" ? (
          <View style={styles.liveBadge} accessibilityLabel="Live vibe">
            <Text style={styles.liveBadgeText}>LIVE</Text>
          </View>
        ) : (
          <View style={styles.recentBadge}>
            <Text style={styles.recentBadgeText}>{vibeDisplayLabel(state)}</Text>
          </View>
        )}
      </View>
      <MediaFrame
        uri={mediaUri}
        accessibilityLabel={`Live vibe by ${item.author_label}`}
        onRetry={onRetryMedia}
      />
      {item.caption ? <Text style={styles.caption}>{item.caption}</Text> : null}
      {item.vibe_tags.length > 0 ? (
        <View style={styles.tags}>
          {item.vibe_tags.slice(0, 3).map((tag) => (
            <View key={tag} style={styles.tag}>
              <Text style={styles.tagText}>{formatVibeTagLabel(tag)}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: "100%",
    borderRadius: 18,
    backgroundColor: colors.surfaceSolid,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderSubtle,
    overflow: "hidden",
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: spacing.md,
    gap: 8,
  },
  cardHeaderCopy: { flexShrink: 1, gap: 2, flexGrow: 1 },
  author: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 14,
  },
  meta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  liveBadge: {
    minHeight: 24,
    paddingHorizontal: 8,
    borderRadius: 6,
    backgroundColor: colors.neon,
    alignItems: "center",
    justifyContent: "center",
  },
  liveBadgeText: {
    color: colors.neonText,
    fontFamily: fontFamilies.geistBold,
    fontSize: 10,
    letterSpacing: 0.8,
  },
  recentBadge: {
    minHeight: 24,
    paddingHorizontal: 8,
    borderRadius: 6,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderMedium,
    alignItems: "center",
    justifyContent: "center",
  },
  recentBadgeText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistBold,
    fontSize: 10,
  },
  mediaFrame: {
    width: "100%",
    aspectRatio: LIVE_VIBE_MEDIA_ASPECT_RATIO,
    backgroundColor: "#111111",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
  },
  fallbackTitle: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 14,
  },
  fallbackButton: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: radii.medium,
    borderWidth: 1,
    borderColor: colors.borderMedium,
    alignItems: "center",
    justifyContent: "center",
  },
  fallbackButtonText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 13,
  },
  caption: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
  },
  tags: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    padding: spacing.md,
  },
  tag: {
    minHeight: 28,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: colors.surfacePressed,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderActive,
    alignItems: "center",
    justifyContent: "center",
  },
  tagText: {
    color: colors.neon,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 11,
  },
});
