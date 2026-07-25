import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useAuth } from "@/auth/AuthProvider";
import { fetchConversations, type ConversationSummary } from "@/features/messages/api";
import { subscribeRealtime } from "@/realtime/client";

function labelFor(item: ConversationSummary): string {
  return (
    item.other_participant.display_name ??
    (item.other_participant.handle ? `@${item.other_participant.handle}` : "Connection")
  );
}

export function ConversationsScreen() {
  const auth = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ["messages", "conversations"],
    queryFn: () => fetchConversations(),
    enabled: auth.status === "authenticated",
  });

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

  return (
    <View style={styles.container}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.title}>Messages</Text>
      <Text style={styles.subtitle}>Private chats after an accepted Calling Card</Text>

      {auth.status !== "authenticated" ? (
        <Text style={styles.help}>Sign in to view messages.</Text>
      ) : null}

      {listQuery.isLoading ? <ActivityIndicator color="#9aa6bf" /> : null}
      {listQuery.error ? (
        <Text style={styles.error}>{(listQuery.error as Error).message}</Text>
      ) : null}

      <FlatList
        data={listQuery.data?.items ?? []}
        keyExtractor={(item) => item.id}
        refreshControl={
          <RefreshControl
            refreshing={listQuery.isRefetching}
            onRefresh={() => void listQuery.refetch()}
            tintColor="#9aa6bf"
          />
        }
        ListEmptyComponent={
          !listQuery.isLoading ? (
            <Text style={styles.help}>No conversations yet. Accept a Calling Card to start.</Text>
          ) : null
        }
        renderItem={({ item }) => (
          <Pressable
            style={styles.row}
            onPress={() => router.push(`/messages/${item.id}`)}
          >
            <View style={styles.rowHeader}>
              <Text style={styles.author}>{labelFor(item)}</Text>
              {item.unread_count > 0 ? (
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>{item.unread_count}</Text>
                </View>
              ) : null}
            </View>
            <Text style={styles.preview} numberOfLines={1}>
              {item.last_message_preview ?? "No messages yet"}
            </Text>
            <Text style={styles.meta}>
              {item.last_message_at
                ? new Date(item.last_message_at).toLocaleString()
                : item.messaging_allowed
                  ? "Ready to message"
                  : "Messaging unavailable"}
            </Text>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b1220", padding: 20, paddingTop: 56 },
  brand: { color: "#f5f7fb", fontSize: 28, fontWeight: "700", letterSpacing: 0.5 },
  title: { color: "#f5f7fb", fontSize: 22, fontWeight: "600", marginTop: 8 },
  subtitle: { color: "#9aa6bf", marginTop: 4, marginBottom: 16 },
  help: { color: "#9aa6bf", marginVertical: 12 },
  error: { color: "#f87171", marginVertical: 8 },
  row: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#1e293b",
    paddingVertical: 14,
  },
  rowHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  author: { color: "#f5f7fb", fontSize: 16, fontWeight: "600" },
  preview: { color: "#cbd5e1", marginTop: 4 },
  meta: { color: "#6f7c99", marginTop: 4, fontSize: 12 },
  badge: {
    backgroundColor: "#334155",
    borderRadius: 10,
    minWidth: 22,
    paddingHorizontal: 6,
    paddingVertical: 2,
    alignItems: "center",
  },
  badgeText: { color: "#f5f7fb", fontSize: 12, fontWeight: "700" },
});
