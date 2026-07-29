import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";
import { useForegroundNotifications } from "@/features/notifications/ForegroundNotificationProvider";
import { ProfileAvatar } from "@/features/connect/ProfileAvatar";
import {
  enqueueSendMessage,
  flushOfflineQueue,
  listActiveQueuedOperations,
} from "@/features/connect/offlineQueue";
import {
  fetchConversations,
  fetchMessages,
  markConversationRead,
  newClientMessageId,
  type MessageSummary,
} from "@/features/messages/api";
import {
  conversationDisplayName,
  formatMessageClock,
  friendlyMessageDeliveryLabel,
} from "@/features/messages/messagesPresentation";
import {
  MESSAGE_BODY_MAX,
  mapQueueStateToMessageUi,
  validateMessageBody,
} from "@/features/messages/messageHelpers";
import { ThreadSkeleton } from "@/features/messages/MessagesSkeleton";
import {
  ConnectionExpiredState,
  MessagesErrorState,
  MessagingDisabledState,
} from "@/features/messages/MessagesStates";
import { subscribeRealtime } from "@/realtime/client";
import { colors, fontFamilies } from "@/theme";

type DisplayMessage = {
  key: string;
  body: string | null;
  mine: boolean;
  createdAt: string;
  statusLabel: string;
  retryable?: boolean;
};

export function ConversationScreen() {
  const { conversationId } = useLocalSearchParams<{ conversationId: string }>();
  const auth = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { setActiveConversationId } = useForegroundNotifications();
  const [draft, setDraft] = useState("");
  const [composerError, setComposerError] = useState<string | null>(null);

  useEffect(() => {
    setActiveConversationId(conversationId ? String(conversationId) : null);
    return () => setActiveConversationId(null);
  }, [conversationId, setActiveConversationId]);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
  });

  const conversationsQuery = useQuery({
    queryKey: ["messages", "conversations"],
    queryFn: () => fetchConversations(),
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

  const conversation = (conversationsQuery.data?.items ?? []).find(
    (item) => item.id === String(conversationId),
  );
  const peerName = conversation
    ? conversationDisplayName(conversation)
    : "Conversation";
  const peerHandle = conversation?.other_participant.handle ?? null;
  const messagingAllowed = conversation?.messaging_allowed ?? true;
  const privacyBlocksMessages =
    meQuery.data?.privacy.allow_messages_from_connections === false;

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
      statusLabel: m.status === "deleted" ? "Removed" : "Sent",
    }));
    const pending = (queueQuery.data ?? [])
      .filter((op) => {
        if (op.operationType !== "message.send") {
          return false;
        }
        try {
          const payload = JSON.parse(op.payloadJson) as { conversation_id?: string };
          return String(payload.conversation_id) === String(conversationId);
        } catch {
          return false;
        }
      })
      .map((op) => {
        let body = "";
        try {
          const payload = JSON.parse(op.payloadJson) as { body?: string };
          body = payload.body ?? "";
        } catch {
          body = "";
        }
        const ui = mapQueueStateToMessageUi(op.state);
        return {
          key: `local-${op.id}`,
          body,
          mine: true,
          createdAt: op.createdAt,
          statusLabel: friendlyMessageDeliveryLabel(op.state),
          retryable: ui === "failed_retryable" || ui === "failed_permanent",
        } satisfies DisplayMessage;
      });
    return [...pending, ...server];
  }, [conversationId, messagesQuery.data?.items, myId, queueQuery.data]);

  const sendMutation = useMutation({
    mutationFn: async () => {
      const validationError = validateMessageBody(draft);
      if (validationError) {
        throw new Error(validationError);
      }
      const clientMessageId = newClientMessageId();
      await enqueueSendMessage({
        conversationId: String(conversationId),
        body: draft.trim(),
        clientMessageId,
      });
      await flushOfflineQueue();
    },
    onSuccess: async () => {
      setDraft("");
      setComposerError(null);
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
    },
    onError: (error: Error) => {
      if (__DEV__) {
        console.warn("[messages.send]", error);
      }
      setComposerError(error.message);
    },
  });

  const retryMutation = useMutation({
    mutationFn: async () => {
      await flushOfflineQueue();
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
    },
  });

  const composerDisabled =
    !messagingAllowed ||
    privacyBlocksMessages ||
    !draft.trim() ||
    sendMutation.isPending;

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={Platform.OS === "ios" ? 8 : 0}
    >
      <View
        style={[styles.container, { paddingTop: insets.top + 4 }]}
        testID="conversation-thread"
      >
        <View style={styles.header}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Go back"
            testID="thread-back"
            onPress={() => {
              if (router.canGoBack()) {
                router.back();
                return;
              }
              router.replace("/messages");
            }}
            style={({ pressed }) => [styles.backBtn, pressed && styles.pressed]}
          >
            <Text style={styles.backText}>←</Text>
          </Pressable>
          <ProfileAvatar displayName={peerName} handle={peerHandle} size={40} />
          <View style={styles.headerCopy}>
            <Text style={styles.title} numberOfLines={1}>
              {peerName}
            </Text>
            {peerHandle ? (
              <Text style={styles.subtitle} numberOfLines={1}>
                @{peerHandle}
              </Text>
            ) : null}
          </View>
        </View>

        {privacyBlocksMessages ? <MessagingDisabledState /> : null}
        {!privacyBlocksMessages && conversation && !messagingAllowed ? (
          <ConnectionExpiredState />
        ) : null}

        {messagesQuery.isLoading ? <ThreadSkeleton /> : null}
        {messagesQuery.isError ? (
          <MessagesErrorState
            title="Couldn’t load this conversation"
            onRetry={() => {
              void messagesQuery.refetch();
            }}
          />
        ) : null}

        {!messagesQuery.isLoading && !messagesQuery.isError ? (
          <FlatList
            inverted
            data={displayMessages}
            keyExtractor={(item) => item.key}
            contentContainerStyle={styles.list}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => (
              <Pressable
                disabled={!item.retryable}
                onPress={() => {
                  if (item.retryable) {
                    retryMutation.mutate();
                  }
                }}
                accessibilityRole={item.retryable ? "button" : "text"}
                accessibilityLabel={
                  item.retryable
                    ? `${item.body ?? "Message"}. ${item.statusLabel}`
                    : undefined
                }
                style={[styles.bubble, item.mine ? styles.mine : styles.theirs]}
              >
                <Text style={[styles.bubbleText, item.mine && styles.mineText]}>
                  {item.body == null ? "Message removed" : item.body}
                </Text>
                <Text style={[styles.bubbleMeta, item.mine && styles.mineMeta]}>
                  {item.statusLabel} · {formatMessageClock(item.createdAt)}
                </Text>
              </Pressable>
            )}
          />
        ) : null}

        <View
          style={[
            styles.composer,
            { paddingBottom: Math.max(insets.bottom, 10) },
          ]}
        >
          <TextInput
            style={styles.input}
            value={draft}
            onChangeText={setDraft}
            placeholder="Message…"
            placeholderTextColor={colors.textSecondary}
            multiline
            maxLength={MESSAGE_BODY_MAX}
            editable={messagingAllowed && !privacyBlocksMessages}
            accessibilityLabel="Message"
            testID="message-composer"
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Send message"
            accessibilityState={{ disabled: composerDisabled }}
            testID="message-send"
            style={({ pressed }) => [
              styles.send,
              composerDisabled && styles.sendDisabled,
              pressed && !composerDisabled && styles.pressed,
            ]}
            disabled={composerDisabled}
            onPress={() => sendMutation.mutate()}
          >
            <Text style={styles.sendText}>
              {sendMutation.isPending ? "…" : "Send"}
            </Text>
          </Pressable>
        </View>
        {composerError ? (
          <Text style={styles.error} accessibilityLiveRegion="polite">
            {composerError}
          </Text>
        ) : null}
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.background },
  container: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
    paddingBottom: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
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
    fontSize: 24,
  },
  subtitle: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
  },
  list: { paddingHorizontal: 16, paddingVertical: 12 },
  bubble: {
    maxWidth: "80%",
    borderRadius: 18,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginVertical: 4,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  mine: {
    alignSelf: "flex-end",
    backgroundColor: "rgba(185, 249, 8, 0.16)",
    borderColor: "rgba(185, 249, 8, 0.28)",
  },
  theirs: {
    alignSelf: "flex-start",
    backgroundColor: colors.surfaceTranslucent,
  },
  bubbleText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
    lineHeight: 21,
  },
  mineText: { color: colors.textPrimary },
  bubbleMeta: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 11,
    marginTop: 4,
  },
  mineMeta: { color: "rgba(143, 163, 157, 0.95)" },
  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    paddingHorizontal: 12,
    paddingTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    backgroundColor: colors.surface,
    borderRadius: 20,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  send: {
    minWidth: 64,
    minHeight: 44,
    borderRadius: 22,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 14,
  },
  sendDisabled: { opacity: 0.4 },
  sendText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 14,
  },
  error: {
    color: colors.danger,
    fontFamily: fontFamilies.geistRegular,
    paddingHorizontal: 16,
    paddingBottom: 8,
    fontSize: 13,
  },
  pressed: { opacity: 0.9 },
});
