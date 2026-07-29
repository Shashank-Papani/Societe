import { Image } from "expo-image";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import type { StoryGroupSummary } from "@/features/stories/api";
import {
  pickStoryDisplayVariant,
  storyGroupAccessibilityLabel,
} from "@/features/stories/storyHelpers";
import { colors, fontFamilies, radii, spacing } from "@/theme";

type Props = {
  groups: StoryGroupSummary[];
  loading?: boolean;
  errorMessage?: string | null;
  canCreate?: boolean;
  venueName?: string | null;
  storiesUnavailable?: boolean;
  onPressYourStory: () => void;
  onPressGroup: (group: StoryGroupSummary) => void;
  onRetry?: () => void;
};

export function StoryRail({
  groups,
  loading = false,
  errorMessage = null,
  canCreate = false,
  venueName = null,
  storiesUnavailable = false,
  onPressYourStory,
  onPressGroup,
  onRetry,
}: Props) {
  return (
    <View testID="story-rail" style={styles.wrap}>
      {loading && groups.length === 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.row}
          testID="story-rail-skeleton"
        >
          {Array.from({ length: 4 }).map((_, index) => (
            <View key={`sk-${index}`} style={styles.item}>
              <View style={[styles.ring, styles.skeletonRing]} />
              <View style={styles.skeletonLabel} />
            </View>
          ))}
        </ScrollView>
      ) : null}

      {errorMessage ? (
        <View style={styles.errorBox} testID="story-rail-error">
          <Text style={styles.errorText}>{errorMessage}</Text>
          {onRetry ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Retry loading Stories"
              onPress={onRetry}
              style={styles.retry}
            >
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {storiesUnavailable ? (
        <Text style={styles.unavailable} testID="story-rail-unavailable">
          Stories are unavailable right now.
        </Text>
      ) : null}

      {!loading && !errorMessage && !storiesUnavailable ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.row}
          testID="story-rail-list"
        >
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={
              canCreate
                ? `Your Story. Share at ${venueName ?? "this venue"}`
                : "Your Story. Verified presence required to post"
            }
            testID="story-rail-your-story"
            onPress={onPressYourStory}
            style={styles.item}
          >
            <View style={[styles.ring, styles.yoursRing]}>
              <Text style={styles.plus}>+</Text>
            </View>
            <Text style={styles.label}>Your Story</Text>
          </Pressable>

          {groups.map((group) => {
            const preview = pickStoryDisplayVariant(group.preview_variants, "image");
            const unviewed = group.unviewed_count > 0;
            return (
              <Pressable
                key={group.group_key}
                accessibilityRole="button"
                accessibilityLabel={storyGroupAccessibilityLabel(group)}
                accessibilityState={{ selected: unviewed }}
                testID={`story-rail-group-${group.group_type}`}
                onPress={() => onPressGroup(group)}
                style={styles.item}
              >
                <View
                  style={[
                    styles.ring,
                    unviewed ? styles.unviewedRing : styles.viewedRing,
                    group.is_official ? styles.officialRing : null,
                    group.group_type === "anon" ? styles.anonRing : null,
                  ]}
                >
                  {group.group_type === "anon" ? (
                    <Text style={styles.anonMark} accessibilityElementsHidden>
                      ?
                    </Text>
                  ) : preview ? (
                    <Image
                      source={{ uri: preview.url }}
                      style={styles.avatar}
                      contentFit="cover"
                    />
                  ) : (
                    <Text style={styles.initial}>
                      {group.author_label.slice(0, 1).toUpperCase()}
                    </Text>
                  )}
                </View>
                <Text style={styles.label} numberOfLines={1}>
                  {group.author_label}
                </Text>
                {group.is_official ? (
                  <Text style={styles.officialBadge} accessibilityLabel="Official">
                    Official
                  </Text>
                ) : null}
                {unviewed ? (
                  <Text style={styles.unviewedHint} accessibilityLabel="Unviewed">
                    New
                  </Text>
                ) : (
                  <Text style={styles.viewedHint} accessibilityLabel="Viewed">
                    Seen
                  </Text>
                )}
              </Pressable>
            );
          })}

          {!loading && groups.length === 0 ? (
            <View style={styles.emptyHint} testID="story-rail-empty">
              <Text style={styles.emptyText}>No active Stories nearby yet.</Text>
            </View>
          ) : null}
        </ScrollView>
      ) : null}

      {loading && groups.length > 0 ? (
        <ActivityIndicator color={colors.neon} style={styles.refreshSpinner} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginBottom: spacing.md,
  },
  row: {
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
    alignItems: "flex-start",
  },
  item: {
    width: 76,
    alignItems: "center",
    gap: 6,
  },
  ring: {
    width: 64,
    height: 64,
    borderRadius: 32,
    borderWidth: 2,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    backgroundColor: colors.surfaceElevated,
  },
  yoursRing: {
    borderColor: colors.neon,
    borderStyle: "dashed",
  },
  unviewedRing: {
    borderColor: colors.neon,
  },
  viewedRing: {
    borderColor: colors.borderSubtle,
  },
  officialRing: {
    borderColor: colors.gold,
  },
  anonRing: {
    borderColor: colors.textSecondary,
  },
  avatar: {
    width: "100%",
    height: "100%",
  },
  plus: {
    color: colors.neon,
    fontSize: 28,
    fontFamily: fontFamilies.geistMedium,
    lineHeight: 32,
  },
  initial: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 22,
  },
  anonMark: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 24,
  },
  label: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 11,
    textAlign: "center",
    width: "100%",
  },
  officialBadge: {
    color: colors.neon,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 9,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  unviewedHint: {
    color: colors.neon,
    fontSize: 9,
    fontFamily: fontFamilies.geistMedium,
  },
  viewedHint: {
    color: colors.textSecondary,
    fontSize: 9,
    fontFamily: fontFamilies.geistRegular,
  },
  skeletonRing: {
    borderColor: colors.borderSubtle,
    backgroundColor: colors.surface,
  },
  skeletonLabel: {
    width: 48,
    height: 8,
    borderRadius: radii.small,
    backgroundColor: colors.surfaceSolid,
  },
  errorBox: {
    marginHorizontal: spacing.lg,
    padding: spacing.md,
    borderRadius: radii.medium,
    backgroundColor: colors.surfaceElevated,
    gap: spacing.sm,
  },
  errorText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  retry: {
    alignSelf: "flex-start",
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.neon,
  },
  retryText: {
    color: colors.neon,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
  },
  unavailable: {
    marginHorizontal: spacing.lg,
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  emptyHint: {
    justifyContent: "center",
    minHeight: 64,
    paddingRight: spacing.lg,
  },
  emptyText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  refreshSpinner: {
    marginTop: spacing.sm,
  },
});
