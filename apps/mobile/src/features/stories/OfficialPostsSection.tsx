import { Image } from "expo-image";
import { openBrowserAsync, WebBrowserPresentationStyle } from "expo-web-browser";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useInfiniteQuery } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { fetchVenueOfficialPosts, type OfficialPostSummary } from "@/features/stories/api";
import {
  isSafeExternalCtaUrl,
  officialPostTypeLabel,
  pickStoryDisplayVariant,
} from "@/features/stories/storyHelpers";
import { colors, fontFamilies, radii, spacing } from "@/theme";

type Props = {
  venueId: string;
  venueName?: string | null;
  enabled?: boolean;
};

function formatPublishedAt(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) {
    return "";
  }
  return new Date(ms).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

async function openSafeCta(url: string) {
  if (!isSafeExternalCtaUrl(url)) {
    Alert.alert("Link unavailable", "This link can’t be opened safely.");
    return;
  }
  Alert.alert("Leave Société?", "Open this venue link in your browser?", [
    { text: "Cancel", style: "cancel" },
    {
      text: "Open",
      onPress: () => {
        void openBrowserAsync(url, {
          presentationStyle: WebBrowserPresentationStyle.AUTOMATIC,
        });
      },
    },
  ]);
}

function OfficialPostCard({
  post,
  onMediaRetry,
}: {
  post: OfficialPostSummary;
  onMediaRetry: () => void;
}) {
  const [failedUri, setFailedUri] = useState<string | null>(null);
  const media = pickStoryDisplayVariant(post.variants, "image");
  const showMedia = media && failedUri !== media.url;

  return (
    <View style={styles.card} testID={`official-post-${post.post_id}`}>
      <View style={styles.cardHeader}>
        <Text style={styles.official}>Official</Text>
        <Text style={styles.type}>{officialPostTypeLabel(post.post_type)}</Text>
      </View>
      <Text style={styles.author}>{post.author_label}</Text>
      {post.title ? <Text style={styles.title}>{post.title}</Text> : null}
      <Text style={styles.body}>{post.body}</Text>
      {showMedia ? (
        <Image
          source={{ uri: media.url }}
          style={styles.media}
          contentFit="cover"
          onError={() => {
            setFailedUri(media.url);
            onMediaRetry();
          }}
          accessibilityLabel="Official post media"
        />
      ) : media ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Retry loading media"
          onPress={() => {
            setFailedUri(null);
            onMediaRetry();
          }}
        >
          <Text style={styles.retry}>Media expired — tap to refresh</Text>
        </Pressable>
      ) : null}
      {post.published_at ? (
        <Text style={styles.meta}>{formatPublishedAt(post.published_at)}</Text>
      ) : null}
      {isSafeExternalCtaUrl(post.call_to_action_url) ? (
        <Pressable
          accessibilityRole="link"
          accessibilityLabel={post.call_to_action_type ?? "Open link"}
          onPress={() => {
            void openSafeCta(String(post.call_to_action_url));
          }}
          style={styles.cta}
          testID="official-post-cta"
        >
          <Text style={styles.ctaText}>
            {(post.call_to_action_type ?? "Learn more").replaceAll("_", " ")}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function OfficialPostsSection({ venueId, enabled = true }: Props) {
  const [urlRetryOnce, setUrlRetryOnce] = useState(false);
  const query = useInfiniteQuery({
    queryKey: ["official-posts", venueId],
    enabled: enabled && Boolean(venueId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => fetchVenueOfficialPosts(venueId, pageParam),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.code === "STORIES_DISABLED") {
        return false;
      }
      return failureCount < 2;
    },
  });

  const posts =
    query.data?.pages.flatMap((page) =>
      page.items.filter((item) => item.publication_status === "published"),
    ) ?? [];

  const onMediaRetry = useCallback(() => {
    if (urlRetryOnce) {
      return;
    }
    setUrlRetryOnce(true);
    void query.refetch();
  }, [urlRetryOnce, query]);

  if (!enabled) {
    return null;
  }

  if (query.isError) {
    const code = query.error instanceof ApiError ? query.error.code : null;
    if (code === "STORIES_DISABLED") {
      return null;
    }
    return (
      <View style={styles.section} testID="official-posts-error">
        <Text style={styles.sectionTitle}>FROM THE VENUE</Text>
        <Text style={styles.empty}>Couldn’t load official updates.</Text>
        <Pressable accessibilityRole="button" onPress={() => void query.refetch()}>
          <Text style={styles.retry}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (query.isLoading) {
    return (
      <View style={styles.section} testID="official-posts-loading">
        <Text style={styles.sectionTitle}>FROM THE VENUE</Text>
        <View style={styles.skeleton} />
        <View style={[styles.skeleton, { width: "70%" }]} />
      </View>
    );
  }

  return (
    <View style={styles.section} testID="official-posts-section">
      <Text style={styles.sectionTitle}>FROM THE VENUE</Text>
      {posts.length === 0 ? (
        <Text style={styles.empty} testID="official-posts-empty">
          No official updates yet.
        </Text>
      ) : (
        posts.map((post) => (
          <OfficialPostCard key={post.post_id} post={post} onMediaRetry={onMediaRetry} />
        ))
      )}
      {query.hasNextPage ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Load more official posts"
          disabled={query.isFetchingNextPage}
          onPress={() => void query.fetchNextPage()}
          style={styles.loadMore}
          testID="official-posts-load-more"
        >
          {query.isFetchingNextPage ? (
            <ActivityIndicator color={colors.neon} />
          ) : (
            <Text style={styles.retry}>Load more</Text>
          )}
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
    letterSpacing: 1,
  },
  empty: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
  },
  skeleton: {
    height: 14,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
    width: "100%",
  },
  card: {
    borderRadius: radii.card,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderSubtle,
    backgroundColor: colors.surfaceElevated,
    padding: spacing.md,
    gap: 8,
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  official: {
    color: colors.gold,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  type: {
    color: colors.textTertiary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 11,
    textTransform: "uppercase",
  },
  author: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 15,
  },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 22,
  },
  body: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    lineHeight: 20,
  },
  media: {
    width: "100%",
    height: 180,
    borderRadius: radii.medium,
    marginTop: 4,
  },
  meta: {
    color: colors.textTertiary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  cta: {
    alignSelf: "flex-start",
    marginTop: 4,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.neon,
  },
  ctaText: {
    color: colors.neon,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 12,
    textTransform: "uppercase",
  },
  retry: {
    color: colors.neon,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  loadMore: {
    alignItems: "center",
    paddingVertical: spacing.sm,
  },
});
