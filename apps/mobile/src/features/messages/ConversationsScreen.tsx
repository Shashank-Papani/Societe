import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/auth/AuthProvider";
import { ProfileAvatar } from "@/features/connect/ProfileAvatar";
import { fetchConversations, type ConversationSummary } from "@/features/messages/api";
import {
  conversationAccessibilityLabel,
  conversationDisplayName,
  conversationPreview,
  formatConversationTimestamp,
} from "@/features/messages/messagesPresentation";
import { ConversationsSkeleton } from "@/features/messages/MessagesSkeleton";
import {
  MessagesEmptyState,
  MessagesErrorState,
} from "@/features/messages/MessagesStates";
import { subscribeRealtime } from "@/realtime/client";
import { colors, fontFamilies } from "@/theme";

export function ConversationsScreen() {
  const auth = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [nowMs, setNowMs] = useState(() => Date.now());

  const listQuery = useQuery({
    queryKey: ["messages", "conversations"],
    queryFn: () => fetchConversations(),
    enabled: auth.status === "authenticated",
  });

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }
    return subscribeRealtime((envelope) => {
      const type = envelope.event_type ?? "";
      if (
        type.startsWith("message.") ||
        type.startsWith("conversation.") ||
        type === "calling_card.accepted"
      ) {
        void queryClient.invalidateQueries({ queryKey: ["messages"] });
      }
    });
  }, [auth.status, queryClient]);

  const unreadTotal = (listQuery.data?.items ?? []).reduce(
    (sum, item) => sum + (item.unread_count > 0 ? item.unread_count : 0),
    0,
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="conversations-screen">
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          testID="conversations-back"
          onPress={() => {
            if (router.canGoBack()) {
              router.back();
              return;
            }
            router.replace("/(tabs)/connect");
          }}
          style={({ pressed }) => [styles.backBtn, pressed && styles.pressed]}
        >
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <View style={styles.headerCopy}>
          <Text style={styles.title} accessibilityRole="header">
            Messages
          </Text>
          {unreadTotal > 0 ? (
            <Text style={styles.unreadMeta}>{unreadTotal} unread</Text>
          ) : null}
        </View>
      </View>

      {auth.status !== "authenticated" ? (
        <Text style={styles.help}>Sign in to view messages.</Text>
      ) : null}

      {auth.status === "authenticated" && listQuery.isLoading ? (
        <View style={styles.padded}>
          <ConversationsSkeleton />
        </View>
      ) : null}

      {auth.status === "authenticated" && listQuery.isError ? (
        <MessagesErrorState
          title="Couldn’t load messages"
          onRetry={() => {
            void listQuery.refetch();
          }}
        />
      ) : null}

      {auth.status === "authenticated" && !listQuery.isLoading && !listQuery.isError ? (
        <FlatList
          data={listQuery.data?.items ?? []}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={listQuery.isRefetching}
              onRefresh={() => void listQuery.refetch()}
              tintColor={colors.lime}
            />
          }
          ListEmptyComponent={<MessagesEmptyState />}
          renderItem={({ item }) => <ConversationRow item={item} nowMs={nowMs} />}
        />
      ) : null}
    </SafeAreaView>
  );
}

function ConversationRow({
  item,
  nowMs,
}: {
  item: ConversationSummary;
  nowMs: number;
}) {
  const router = useRouter();
  const name = conversationDisplayName(item);
  const preview = conversationPreview(item);
  const time = formatConversationTimestamp(item.last_message_at, nowMs);
  const unread = item.unread_count > 0;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={conversationAccessibilityLabel(item)}
      testID={`conversation-row-${item.id}`}
      onPress={() => router.push(`/messages/${item.id}`)}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      <ProfileAvatar
        displayName={name}
        handle={item.other_participant.handle}
        size={48}
      />
      <View style={styles.rowCopy}>
        <View style={styles.rowTop}>
          <Text style={styles.name} numberOfLines={1}>
            {name}
          </Text>
          {time ? <Text style={styles.time}>{time}</Text> : null}
        </View>
        <View style={styles.rowBottom}>
          <Text
            style={[styles.preview, unread && styles.previewUnread]}
            numberOfLines={1}
          >
            {preview}
          </Text>
          {unread ? (
            <View
              style={styles.unreadDot}
              accessibilityLabel={`${item.unread_count} unread`}
              testID={`conversation-unread-${item.id}`}
            >
              <Text style={styles.unreadCount}>
                {item.unread_count > 99 ? "99+" : String(item.unread_count)}
              </Text>
            </View>
          ) : null}
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
    paddingTop: 4,
    paddingBottom: 12,
  },
  backBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  backText: {
    color: colors.textPrimary,
    fontSize: 20,
    fontFamily: fontFamilies.geistSemiBold,
  },
  headerCopy: { flex: 1, gap: 2 },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 34,
  },
  unreadMeta: {
    color: colors.lime,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
  },
  help: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    paddingHorizontal: 20,
  },
  padded: { paddingHorizontal: 20 },
  list: { paddingHorizontal: 20, paddingBottom: 32, flexGrow: 1 },
  row: {
    minHeight: 72,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  rowCopy: { flex: 1, gap: 4 },
  rowTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  rowBottom: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  name: {
    flex: 1,
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 16,
  },
  time: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  preview: {
    flex: 1,
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  previewUnread: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistMedium,
  },
  unreadDot: {
    minWidth: 22,
    minHeight: 22,
    borderRadius: 11,
    paddingHorizontal: 6,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
  },
  unreadCount: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 11,
  },
  pressed: { opacity: 0.9 },
});
