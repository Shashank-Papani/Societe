/**
 * Notification Center — inbox list with read / dismiss / deep-link navigation.
 */

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter, type Href } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "@/api/client";
import { colors, fontFamilies, spacing } from "@/theme";
import {
  dismissNotification,
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "./api";
import { deepLinkToHref, parseNotificationDeepLink } from "./deepLinks";
import {
  actorDisplayLabel,
  categoryLabel,
  markAllNotificationsRead as markAllLocal,
  markNotificationReadInList,
  mergeNotificationPages,
  notificationRowAccessibilityLabel,
  relativeTimestamp,
  removeNotificationItem,
} from "./notificationHelpers";
import type { NotificationItem } from "./notificationSchemas";
import { useNotificationsOptional } from "./NotificationsProvider";

export function NotificationCenterScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const notificationsCtx = useNotificationsOptional();
  const [actionError, setActionError] = useState<string | null>(null);

  const listQuery = useInfiniteQuery({
    queryKey: ["notifications", "list", { unread_only: false }],
    queryFn: ({ pageParam }) =>
      fetchNotifications({ cursor: pageParam ?? null, limit: 20 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });

  const items = useMemo(
    () => mergeNotificationPages(listQuery.data?.pages ?? []),
    [listQuery.data?.pages],
  );

  const invalidateAll = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    notificationsCtx?.refreshInboxHints();
  }, [notificationsCtx, queryClient]);

  const readMutation = useMutation({
    mutationFn: (id: string) => markNotificationRead(id),
    onSuccess: () => invalidateAll(),
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => dismissNotification(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ["notifications", "list"] });
      const previous = queryClient.getQueryData(["notifications", "list", { unread_only: false }]);
      queryClient.setQueryData(
        ["notifications", "list", { unread_only: false }],
        (old: { pages?: { items: NotificationItem[]; next_cursor: string | null }[] } | undefined) => {
          if (!old?.pages) {
            return old;
          }
          return {
            ...old,
            pages: old.pages.map((page) => ({
              ...page,
              items: removeNotificationItem(page.items, id),
            })),
          };
        },
      );
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) {
        queryClient.setQueryData(
          ["notifications", "list", { unread_only: false }],
          ctx.previous,
        );
      }
      setActionError("Could not dismiss notification.");
    },
    onSettled: () => invalidateAll(),
  });

  const readAllMutation = useMutation({
    mutationFn: () => markAllNotificationsRead(),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["notifications", "list"] });
      queryClient.setQueryData(
        ["notifications", "list", { unread_only: false }],
        (old: { pages?: { items: NotificationItem[]; next_cursor: string | null }[] } | undefined) => {
          if (!old?.pages) {
            return old;
          }
          return {
            ...old,
            pages: old.pages.map((page) => ({
              ...page,
              items: markAllLocal(page.items),
            })),
          };
        },
      );
      queryClient.setQueryData(["notifications", "unread-count"], (old: unknown) => {
        if (old && typeof old === "object" && "by_category" in old) {
          return { total: 0, by_category: (old as { by_category: Record<string, number> }).by_category };
        }
        return { total: 0, by_category: {} };
      });
    },
    onError: () => setActionError("Could not mark all as read."),
    onSettled: () => invalidateAll(),
  });

  const openItem = useCallback(
    async (item: NotificationItem) => {
      setActionError(null);
      if (!item.read) {
        try {
          queryClient.setQueryData(
            ["notifications", "list", { unread_only: false }],
            (old: { pages?: { items: NotificationItem[]; next_cursor: string | null }[] } | undefined) => {
              if (!old?.pages) {
                return old;
              }
              return {
                ...old,
                pages: old.pages.map((page) => ({
                  ...page,
                  items: markNotificationReadInList(page.items, item.notification_id),
                })),
              };
            },
          );
          await readMutation.mutateAsync(item.notification_id);
        } catch {
          // Navigation may continue; reconcile on next refetch.
        }
      }
      const parsed = parseNotificationDeepLink(item.deep_link);
      if (!parsed) {
        setActionError("This notification link is unavailable.");
        return;
      }
      if (parsed.kind === "venue_claim" || parsed.kind === "organization_invitation") {
        router.push(deepLinkToHref(parsed) as never);
        return;
      }
      router.push(deepLinkToHref(parsed) as never);
    },
    [queryClient, readMutation, router],
  );

  const errorMessage =
    actionError ??
    (listQuery.error instanceof ApiError
      ? listQuery.error.message
      : listQuery.isError
        ? "Could not load notifications."
        : null);

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          onPress={() => router.back()}
          style={styles.backButton}
          testID="notifications-back"
        >
          <Text style={styles.backText}>Back</Text>
        </Pressable>
        <Text style={styles.title} accessibilityRole="header">
          Notifications
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Mark all notifications as read"
          onPress={() => readAllMutation.mutate()}
          disabled={readAllMutation.isPending || items.every((i) => i.read)}
          style={styles.readAll}
          testID="notifications-read-all"
        >
          <Text style={styles.readAllText}>Read all</Text>
        </Pressable>
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Open notification preferences"
        onPress={() => router.push("/notifications/preferences" as Href)}
        style={styles.prefsLink}
        testID="notifications-open-preferences"
      >
        <Text style={styles.prefsLinkText}>Preferences</Text>
      </Pressable>

      {listQuery.isLoading && items.length === 0 ? (
        <View style={styles.centered} testID="notifications-skeleton">
          <ActivityIndicator color={colors.neon} />
        </View>
      ) : null}

      {errorMessage && items.length === 0 ? (
        <View style={styles.centered}>
          <Text style={styles.emptyTitle}>Something went wrong</Text>
          <Text style={styles.emptyBody}>{errorMessage}</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Retry loading notifications"
            onPress={() => void listQuery.refetch()}
            style={styles.retry}
            testID="notifications-retry"
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : null}

      {!listQuery.isLoading && items.length === 0 && !errorMessage ? (
        <View style={styles.centered} testID="notifications-empty">
          <Text style={styles.emptyTitle}>You are all caught up</Text>
          <Text style={styles.emptyBody}>New Calling Cards, messages, and Stories will land here.</Text>
        </View>
      ) : null}

      {items.length > 0 ? (
        <FlatList
          data={items}
          keyExtractor={(item) => item.notification_id}
          contentContainerStyle={styles.listContent}
          refreshControl={
            <RefreshControl
              refreshing={listQuery.isRefetching && !listQuery.isFetchingNextPage}
              onRefresh={() => void listQuery.refetch()}
              tintColor={colors.neon}
            />
          }
          onEndReached={() => {
            if (listQuery.hasNextPage && !listQuery.isFetchingNextPage) {
              void listQuery.fetchNextPage();
            }
          }}
          onEndReachedThreshold={0.4}
          ListFooterComponent={
            listQuery.isFetchingNextPage ? (
              <ActivityIndicator color={colors.neon} style={{ marginVertical: 16 }} />
            ) : null
          }
          renderItem={({ item }) => (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={notificationRowAccessibilityLabel(item)}
              accessibilityState={{ selected: !item.read }}
              onPress={() => void openItem(item)}
              onLongPress={() => dismissMutation.mutate(item.notification_id)}
              style={[styles.row, !item.read && styles.rowUnread]}
              testID={`notification-row-${item.notification_id}`}
            >
              <View style={styles.rowMain}>
                <Text style={styles.rowCategory}>{categoryLabel(item.category)}</Text>
                <Text style={styles.rowTitle} numberOfLines={2}>
                  {item.title}
                </Text>
                <Text style={styles.rowBody} numberOfLines={2}>
                  {item.body}
                </Text>
                <View style={styles.metaRow}>
                  <Text style={styles.metaText}>
                    {actorDisplayLabel(item)} · {relativeTimestamp(item.latest_event_at)}
                  </Text>
                  {item.occurrence_count > 1 ? (
                    <Text style={styles.countChip}>{item.occurrence_count}</Text>
                  ) : null}
                  {!item.read ? (
                    <Text style={styles.unreadChip} accessibilityLabel="Unread">
                      Unread
                    </Text>
                  ) : null}
                </View>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Dismiss notification"
                onPress={() => dismissMutation.mutate(item.notification_id)}
                style={styles.dismiss}
                hitSlop={8}
                testID={`notification-dismiss-${item.notification_id}`}
              >
                <Text style={styles.dismissText}>✕</Text>
              </Pressable>
            </Pressable>
          )}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  backButton: { minWidth: 64, paddingVertical: 8 },
  backText: { color: colors.neon, fontFamily: fontFamilies.geistMedium, fontSize: 15 },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
  },
  readAll: { minWidth: 64, alignItems: "flex-end", paddingVertical: 8 },
  readAllText: { color: colors.textSecondary, fontFamily: fontFamilies.geistMedium, fontSize: 13 },
  prefsLink: { paddingHorizontal: spacing.md, paddingBottom: spacing.sm },
  prefsLinkText: { color: colors.neon, fontFamily: fontFamilies.geistMedium, fontSize: 14 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32, gap: 10 },
  emptyTitle: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 18,
    textAlign: "center",
  },
  emptyBody: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    textAlign: "center",
    lineHeight: 20,
  },
  retry: {
    marginTop: 8,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.borderActive,
  },
  retryText: { color: colors.neon, fontFamily: fontFamilies.geistMedium },
  listContent: { paddingHorizontal: spacing.md, paddingBottom: 40, gap: 8 },
  row: {
    flexDirection: "row",
    gap: 10,
    padding: 14,
    borderRadius: 16,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  rowUnread: {
    borderColor: colors.borderActive,
    backgroundColor: colors.surfaceElevated,
  },
  rowMain: { flex: 1, gap: 4 },
  rowCategory: {
    color: colors.textTertiary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  rowTitle: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 15,
  },
  rowBody: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    lineHeight: 18,
  },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4, flexWrap: "wrap" },
  metaText: { color: colors.textTertiary, fontFamily: fontFamilies.geistRegular, fontSize: 12 },
  countChip: {
    color: colors.neonText,
    backgroundColor: colors.neon,
    overflow: "hidden",
    borderRadius: 8,
    paddingHorizontal: 6,
    paddingVertical: 1,
    fontSize: 11,
    fontFamily: fontFamilies.geistMedium,
  },
  unreadChip: {
    color: colors.neon,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 11,
  },
  dismiss: { padding: 4, alignSelf: "flex-start" },
  dismissText: { color: colors.textTertiary, fontSize: 14 },
});
