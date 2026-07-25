import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";
import {
  enqueueSendMessage,
  flushOfflineQueue,
  listActiveQueuedOperations,
} from "@/features/connect/offlineQueue";
import {
  fetchMessages,
  markConversationRead,
  newClientMessageId,
  type MessageSummary,
} from "@/features/messages/api";
import { subscribeRealtime } from "@/realtime/client";

const BODY_MAX = 2000;

type DisplayMessage = {
  key: string;
  body: string | null;
  mine: boolean;
  createdAt: string;
  statusLabel: string;
  retryClientMessageId?: string;
};

export function ConversationScreen() {
  const { conversationId } = useLocalSearchParams<{ conversationId: string }>();
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [composerError, setComposerError] = useState<string | null>(null);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
  });

  const messagesQuery = useQuery({
    queryKey: ["messages", conversationId, "thread"],
    queryFn: () => fetchMessages(String(conversationId)),
    enabled: auth.status === "authenticated" && Boolean(conversationId),
  });

  const queueQuery = useQuery({
    queryKey: ["messages", "queue", conversationId],
    queryFn: listActiveQueuedOperations,
    enabled: auth.status === "authenticated",
    refetchInterval: 4_000,
  });

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }
    return subscribeRealtime((envelope) => {
      const type = envelope.event_type ?? "";
      if (type.startsWith("message.") || type.startsWith("conversation.")) {
        void queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
        void queryClient.invalidateQueries({ queryKey: ["messages", "conversations"] });
      }
    });
  }, [auth.status, conversationId, queryClient]);

  useEffect(() => {
    if (auth.status !== "authenticated" || !conversationId) {
      return;
    }
    const items = messagesQuery.data?.items ?? [];
    if (items.length === 0) {
      return;
    }
    const newest = items[0];
    void markConversationRead(String(conversationId), newest.id).then(() => {
      void queryClient.invalidateQueries({ queryKey: ["messages", "conversations"] });
    });
  }, [auth.status, conversationId, messagesQuery.data?.items, queryClient]);

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }
    const timer = setInterval(() => {
      void flushOfflineQueue().then(() => {
        void queryClient.invalidateQueries({ queryKey: ["messages"] });
      });
    }, 5_000);
    return () => clearInterval(timer);
  }, [auth.status, queryClient]);

  const myId = meQuery.data?.id;

  const displayMessages: DisplayMessage[] = useMemo(() => {
    const server = (messagesQuery.data?.items ?? []).map((m: MessageSummary) => ({
      key: m.id,
      body: m.status === "deleted" ? null : m.body,
      mine: m.sender_user_id === myId,
      createdAt: m.created_at,
      statusLabel: m.status === "deleted" ? "Deleted" : "Sent",
    }));
    const pending = (queueQuery.data ?? [])
      .filter(
        (op) =>
          op.operationType === "message.send" &&
          String(JSON.parse(op.payloadJson).conversation_id) === String(conversationId),
      )
      .map((op) => {
        const payload = JSON.parse(op.payloadJson) as {
          body?: string;
          client_message_id?: string;
        };
        const label =
          op.state === "failed_permanent"
            ? "Failed"
            : op.state === "failed_retryable"
              ? "Failed · retry"
              : op.state === "sending"
                ? "Sending…"
                : "Queued";
        return {
          key: `local-${op.id}`,
          body: payload.body ?? "",
          mine: true,
          createdAt: op.createdAt,
          statusLabel: label,
          retryClientMessageId:
            op.state === "failed_retryable" || op.state === "failed_permanent"
              ? (payload.client_message_id ?? op.idempotencyKey)
              : undefined,
        } satisfies DisplayMessage;
      });
    return [...pending, ...server];
  }, [conversationId, messagesQuery.data?.items, myId, queueQuery.data]);

  const sendMutation = useMutation({
    mutationFn: async () => {
      const trimmed = draft.trim();
      if (!trimmed) {
        throw new Error("Message cannot be empty.");
      }
      if (trimmed.length > BODY_MAX) {
        throw new Error(`Message must be at most ${BODY_MAX} characters.`);
      }
      const clientMessageId = newClientMessageId();
      await enqueueSendMessage({
        conversationId: String(conversationId),
        body: trimmed,
        clientMessageId,
      });
      await flushOfflineQueue();
    },
    onSuccess: async () => {
      setDraft("");
      setComposerError(null);
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
    },
    onError: (error: Error) => setComposerError(error.message),
  });

  const retryMutation = useMutation({
    mutationFn: async () => {
      await flushOfflineQueue();
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
    },
  });

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Conversation</Text>
      {messagesQuery.isLoading ? <ActivityIndicator color="#9aa6bf" /> : null}
      {messagesQuery.error ? (
        <Text style={styles.error}>{(messagesQuery.error as Error).message}</Text>
      ) : null}

      <FlatList
        inverted
        data={displayMessages}
        keyExtractor={(item) => item.key}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => (
          <View style={[styles.bubble, item.mine ? styles.mine : styles.theirs]}>
            <Text style={styles.bubbleText}>
              {item.body == null ? "Message removed" : item.body}
            </Text>
            <Text style={styles.bubbleMeta}>
              {item.statusLabel} · {new Date(item.createdAt).toLocaleTimeString()}
            </Text>
            {item.retryClientMessageId ? (
              <Pressable onPress={() => retryMutation.mutate()}>
                <Text style={styles.retry}>Retry</Text>
              </Pressable>
            ) : null}
          </View>
        )}
      />

      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          value={draft}
          onChangeText={setDraft}
          placeholder="Message"
          placeholderTextColor="#6f7c99"
          multiline
          maxLength={BODY_MAX}
        />
        <Pressable
          style={[
            styles.send,
            (!draft.trim() || sendMutation.isPending) && styles.sendDisabled,
          ]}
          disabled={!draft.trim() || sendMutation.isPending}
          onPress={() => sendMutation.mutate()}
        >
          <Text style={styles.sendText}>{sendMutation.isPending ? "…" : "Send"}</Text>
        </Pressable>
      </View>
      {composerError ? <Text style={styles.error}>{composerError}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b1220", paddingTop: 56 },
  title: { color: "#f5f7fb", fontSize: 20, fontWeight: "600", paddingHorizontal: 20 },
  list: { paddingHorizontal: 16, paddingVertical: 12 },
  bubble: {
    maxWidth: "80%",
    borderRadius: 12,
    padding: 10,
    marginVertical: 4,
  },
  mine: { alignSelf: "flex-end", backgroundColor: "#1e3a5f" },
  theirs: { alignSelf: "flex-start", backgroundColor: "#1e293b" },
  bubbleText: { color: "#f5f7fb" },
  bubbleMeta: { color: "#6f7c99", fontSize: 11, marginTop: 4 },
  retry: { color: "#93c5fd", marginTop: 4 },
  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    padding: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "#1e293b",
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 120,
    color: "#f5f7fb",
    backgroundColor: "#111827",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  send: {
    backgroundColor: "#334155",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  sendDisabled: { opacity: 0.4 },
  sendText: { color: "#f5f7fb", fontWeight: "600" },
  error: { color: "#f87171", paddingHorizontal: 16, paddingBottom: 8 },
});
