import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";
import {
  blockUser,
  fetchCallingCardInbox,
  fetchCallingCardSent,
  fetchDiscoverableUsers,
  newIdempotencyKey,
  type CallingCardReasonCode,
  type CallingCardSummary,
  type DiscoverableUser,
} from "@/features/connect/api";
import { CallingCardComposerSheet } from "@/features/connect/CallingCardComposerSheet";
import { CallingCardRow } from "@/features/connect/CallingCardRow";
import {
  friendlyConnectStateLabel,
  presenceContextLabel,
} from "@/features/connect/connectPresentation";
import { ConnectSkeleton } from "@/features/connect/ConnectSkeleton";
import {
  ConnectEmptyConnections,
  ConnectEmptyNearby,
  ConnectEmptyPending,
  ConnectEmptyPresence,
  ConnectErrorState,
  ConnectGhostState,
} from "@/features/connect/ConnectStates";
import { DeveloperDiagnostics } from "@/features/connect/DeveloperDiagnostics";
import { NearbyPersonCard } from "@/features/connect/NearbyPersonCard";
import {
  enqueueCancelCallingCard,
  enqueueCreateCallingCard,
  enqueueRespondCallingCard,
  flushOfflineQueue,
  listActiveQueuedOperations,
  reconcileRespondOperationsWithCards,
  type QueuedOperation,
} from "@/features/connect/offlineQueue";
import type { ConnectUiState } from "@/features/connect/queueHelpers";
import { createConversation } from "@/features/messages/api";
import { fetchPresenceMe } from "@/features/presence/api";
import { subscribeRealtime } from "@/realtime/client";
import { tabScreenBottomPadding } from "@/navigation/tabBar";
import { colors, fontFamilies } from "@/theme";

const INBOX_POLL_MS = 12_000;
const QUEUE_FLUSH_MS = 8_000;

type NearbyRelation = "available" | "pending" | "connected" | "sending";

function localOpUiState(op: QueuedOperation): ConnectUiState {
  switch (op.state) {
    case "queued":
      return "queued";
    case "sending":
      return "sending";
    case "failed_retryable":
      return "failed_retryable";
    case "failed_permanent":
      return "failed_permanent";
    case "expired":
      return "expired";
    case "acknowledged":
    case "server_confirmed":
      return "delivered";
    default:
      return "queued";
  }
}

function parsePayload(op: QueuedOperation): Record<string, unknown> {
  try {
    return JSON.parse(op.payloadJson) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function activeCreateOpForRecipient(
  ops: QueuedOperation[],
  userId: string,
): QueuedOperation | null {
  return (
    ops.find((item) => {
      if (item.operationType !== "calling_card.create") {
        return false;
      }
      if (!["queued", "sending", "failed_retryable"].includes(item.state)) {
        return false;
      }
      return String(parsePayload(item).recipient_user_id ?? "") === userId;
    }) ?? null
  );
}

function queueHintForRecipient(ops: QueuedOperation[], userId: string): string | null {
  const op = activeCreateOpForRecipient(ops, userId);
  return op ? friendlyConnectStateLabel(localOpUiState(op)) : null;
}

function queueHintForCard(ops: QueuedOperation[], cardId: string): string | null {
  const op = ops.find((item) => {
    if (
      item.operationType !== "calling_card.respond" &&
      item.operationType !== "calling_card.cancel"
    ) {
      return false;
    }
    return String(parsePayload(item).calling_card_id ?? "") === cardId;
  });
  return op ? friendlyConnectStateLabel(localOpUiState(op)) : null;
}

function otherPartyId(card: CallingCardSummary, myId: string | undefined): string {
  if (!myId) {
    return card.sender_user_id;
  }
  return card.sender_user_id === myId ? card.recipient_user_id : card.sender_user_id;
}

/** Defense-in-depth: one connection row per peer (backend is authoritative). */
function dedupeConnectionsByPeer(
  cards: CallingCardSummary[],
  myId: string | undefined,
): CallingCardSummary[] {
  const byPeer = new Map<string, CallingCardSummary>();
  for (const card of cards) {
    const peer = otherPartyId(card, myId);
    const existing = byPeer.get(peer);
    if (!existing) {
      byPeer.set(peer, card);
      continue;
    }
    const existingTs = Date.parse(existing.created_at);
    const nextTs = Date.parse(card.created_at);
    if (nextTs >= existingTs) {
      byPeer.set(peer, card);
    }
  }
  return [...byPeer.values()];
}

function relationForPerson(input: {
  userId: string;
  pendingPeerIds: Set<string>;
  connectedPeerIds: Set<string>;
  localOps: QueuedOperation[];
  sendingUserId: string | null;
}): NearbyRelation {
  if (input.connectedPeerIds.has(input.userId)) {
    return "connected";
  }
  if (input.pendingPeerIds.has(input.userId)) {
    return "pending";
  }
  if (input.sendingUserId === input.userId) {
    return "sending";
  }
  if (activeCreateOpForRecipient(input.localOps, input.userId)) {
    return "pending";
  }
  return "available";
}

export function ConnectScreen() {
  const auth = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const bottomPad = tabScreenBottomPadding(insets.bottom);
  const [composerPerson, setComposerPerson] = useState<DiscoverableUser | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const presenceQuery = useQuery({
    queryKey: ["presence", "me"],
    queryFn: fetchPresenceMe,
    enabled: auth.status === "authenticated",
    refetchInterval: 30_000,
  });

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
  });

  const canSend =
    presenceQuery.data?.state === "verified" &&
    Boolean(presenceQuery.data.social_features_enabled) &&
    Boolean(presenceQuery.data.venue?.id);

  const ghostOn = Boolean(
    meQuery.data?.privacy.ghost_mode || meQuery.data?.privacy.effective.ghost_mode_overrides,
  );
  const exited =
    presenceQuery.data != null &&
    !["verified", "provisional"].includes(presenceQuery.data.state);

  const discoverQuery = useQuery({
    queryKey: ["connect", "discoverable"],
    queryFn: fetchDiscoverableUsers,
    enabled: auth.status === "authenticated" && canSend && !ghostOn,
    refetchInterval: INBOX_POLL_MS,
  });

  const inboxQuery = useQuery({
    queryKey: ["connect", "inbox"],
    queryFn: fetchCallingCardInbox,
    enabled: auth.status === "authenticated" && !ghostOn,
    refetchInterval: INBOX_POLL_MS,
  });

  const sentQuery = useQuery({
    queryKey: ["connect", "sent"],
    queryFn: fetchCallingCardSent,
    enabled: auth.status === "authenticated",
    refetchInterval: INBOX_POLL_MS,
  });

  const queueQuery = useQuery({
    queryKey: ["connect", "queue"],
    queryFn: listActiveQueuedOperations,
    enabled: auth.status === "authenticated",
    refetchInterval: QUEUE_FLUSH_MS,
  });

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }
    const tick = () => {
      void flushOfflineQueue()
        .then((result) => {
          if (result.acknowledged > 0 || result.expired > 0 || result.failedPermanent > 0) {
            void queryClient.invalidateQueries({ queryKey: ["connect"] });
          } else {
            void queryClient.invalidateQueries({ queryKey: ["connect", "queue"] });
          }
        })
        .catch(() => {
          // Keep UI usable offline; next tick retries.
        });
    };
    tick();
    const timer = setInterval(tick, QUEUE_FLUSH_MS);
    return () => clearInterval(timer);
  }, [auth.status, queryClient]);

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }
    return subscribeRealtime((envelope) => {
      const type = envelope.event_type ?? "";
      if (
        type.startsWith("calling_card.") ||
        type.startsWith("user.") ||
        type.startsWith("conversation.") ||
        type.startsWith("message.")
      ) {
        void queryClient.invalidateQueries({ queryKey: ["connect"] });
        void queryClient.invalidateQueries({ queryKey: ["messages"] });
      }
    });
  }, [auth.status, queryClient]);

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }
    const cards = [...(inboxQuery.data?.items ?? []), ...(sentQuery.data?.items ?? [])];
    if (cards.length === 0) {
      return;
    }
    void reconcileRespondOperationsWithCards(cards).then((cleared) => {
      if (cleared > 0) {
        void queryClient.invalidateQueries({ queryKey: ["connect", "queue"] });
      }
    });
  }, [auth.status, inboxQuery.data?.items, sentQuery.data?.items, queryClient]);

  const openMessageMutation = useMutation({
    mutationFn: async (otherUserId: string) => {
      const conversation = await createConversation({ otherUserId });
      return conversation.id;
    },
    onSuccess: (id) => {
      setActionError(null);
      router.push(`/messages/${id}`);
    },
    onError: (error: Error) => {
      if (__DEV__) {
        console.warn("[connect.message]", error);
      }
      if (error instanceof ApiError) {
        if (error.code === "CONNECTION_REQUIRED") {
          setActionError("This connection is no longer active. Send a new Calling Card to reconnect.");
          void queryClient.invalidateQueries({ queryKey: ["connect"] });
          return;
        }
        if (error.code === "MESSAGING_BLOCKED") {
          setActionError("Messaging isn’t available while a block is in place.");
          void queryClient.invalidateQueries({ queryKey: ["connect"] });
          return;
        }
        if (error.code === "MESSAGING_DISABLED") {
          setActionError("Messaging is turned off in privacy settings.");
          return;
        }
        setActionError(error.message || "Couldn’t open messages. Try again.");
        return;
      }
      setActionError("Couldn’t open messages. Try again.");
    },
  });

  const invalidateConnect = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["connect"] }),
      queryClient.invalidateQueries({ queryKey: ["presence", "me"] }),
    ]);
  };

  const sendMutation = useMutation({
    mutationFn: async (input: {
      user: DiscoverableUser;
      reasonCode: CallingCardReasonCode | null;
      customMessage: string | null;
    }) => {
      const key = newIdempotencyKey();
      await enqueueCreateCallingCard({
        recipientUserId: input.user.user_id,
        reasonCode: input.reasonCode,
        customMessage: input.customMessage,
        idempotencyKey: key,
      });
      await flushOfflineQueue();
    },
    onSuccess: async () => {
      setActionError(null);
      setComposerError(null);
      setComposerPerson(null);
      await invalidateConnect();
    },
    onError: (error: Error) => {
      if (__DEV__) {
        console.warn("[connect.send]", error);
      }
      if (error instanceof ApiError && error.code === "CALLING_CARD_ALREADY_CONNECTED") {
        setComposerPerson(null);
        setActionError(null);
        void invalidateConnect();
        return;
      }
      if (error instanceof ApiError && error.code === "CALLING_CARD_ALREADY_ACTIVE") {
        setComposerPerson(null);
        setActionError(null);
        void invalidateConnect();
        return;
      }
      // Keep composer open so the entered message is preserved.
      setComposerError("Couldn’t send Calling Card. Try again.");
    },
  });

  const respondMutation = useMutation({
    mutationFn: async (input: { card: CallingCardSummary; decision: "accept" | "decline" }) => {
      const key = newIdempotencyKey();
      await enqueueRespondCallingCard({
        callingCardId: input.card.id,
        decision: input.decision,
        action: input.decision === "accept" ? "accept_only" : null,
        idempotencyKey: key,
        expiresAt: input.card.expires_at,
      });
      await flushOfflineQueue();
    },
    onSuccess: async () => {
      setActionError(null);
      await invalidateConnect();
    },
    onError: (error: Error) => {
      if (__DEV__) {
        console.warn("[connect.respond]", error);
      }
      setActionError("Couldn’t update Calling Card. Try again.");
    },
  });

  const cancelMutation = useMutation({
    mutationFn: async (card: CallingCardSummary) => {
      const key = newIdempotencyKey();
      await enqueueCancelCallingCard({
        callingCardId: card.id,
        idempotencyKey: key,
        expiresAt: card.expires_at,
      });
      await flushOfflineQueue();
    },
    onSuccess: async () => {
      setActionError(null);
      await invalidateConnect();
    },
    onError: (error: Error) => {
      if (__DEV__) {
        console.warn("[connect.cancel]", error);
      }
      setActionError("Couldn’t cancel Calling Card. Try again.");
    },
  });

  const blockMutation = useMutation({
    mutationFn: (userId: string) => blockUser(userId, "harassment"),
    onSuccess: async () => {
      setActionError(null);
      await invalidateConnect();
    },
    onError: (error: Error) => {
      if (__DEV__) {
        console.warn("[connect.block]", error);
      }
      setActionError("Couldn’t update block settings. Try again.");
    },
  });

  const venueName = presenceQuery.data?.venue?.name ?? null;
  const pendingInbox = (inboxQuery.data?.items ?? []).filter((c) => c.status === "pending");
  const acceptedInbox = (inboxQuery.data?.items ?? []).filter(
    (c) => c.status === "accepted" && c.has_active_grant !== false,
  );
  const acceptedSent = (sentQuery.data?.items ?? []).filter(
    (c) => c.status === "accepted" && c.has_active_grant !== false,
  );
  const pendingSent = (sentQuery.data?.items ?? []).filter((c) => c.status === "pending");
  const localOps = queueQuery.data ?? [];
  const myId = meQuery.data?.id;
  const peopleById = useMemo(() => {
    const map = new Map<string, DiscoverableUser>();
    for (const person of discoverQuery.data?.items ?? []) {
      map.set(person.user_id, person);
    }
    return map;
  }, [discoverQuery.data?.items]);

  const pendingPeerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const card of pendingInbox) {
      ids.add(card.sender_user_id);
    }
    for (const card of pendingSent) {
      ids.add(card.recipient_user_id);
    }
    return ids;
  }, [pendingInbox, pendingSent]);

  const connectedPeerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const card of [...acceptedInbox, ...acceptedSent]) {
      ids.add(otherPartyId(card, myId));
    }
    return ids;
  }, [acceptedInbox, acceptedSent, myId]);

  const connections = useMemo(
    () => dedupeConnectionsByPeer([...acceptedInbox, ...acceptedSent], myId),
    [acceptedInbox, acceptedSent, myId],
  );

  const contextLine = useMemo(
    () =>
      presenceContextLabel({
        venueName,
        verified: Boolean(canSend),
        ghostOn,
      }),
    [venueName, canSend, ghostOn],
  );

  const loadingShell =
    auth.status === "initializing" ||
    (auth.status === "authenticated" && presenceQuery.isLoading && !presenceQuery.data);

  const openComposer = (user: DiscoverableUser) => {
    setComposerError(null);
    setComposerPerson(user);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="connect-screen">
      <ScrollView
        contentContainerStyle={[styles.content, { paddingBottom: bottomPad }]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <View style={styles.headerCopy}>
            <Text style={styles.title} accessibilityRole="header">
              Connect
            </Text>
            {contextLine ? (
              <Text style={styles.context} numberOfLines={2}>
                {contextLine}
              </Text>
            ) : null}
          </View>
          <View style={styles.headerActions}>
            {auth.status === "authenticated" ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Messages"
                testID="connect-messages"
                onPress={() => router.push("/messages")}
                style={({ pressed }) => [styles.headerBtn, pressed && styles.pressed]}
              >
                <Text style={styles.headerBtnText}>Messages</Text>
              </Pressable>
            ) : null}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Profile settings"
              testID="connect-settings"
              onPress={() => router.push("/(tabs)/profile")}
              hitSlop={8}
              style={({ pressed }) => [styles.iconBtn, pressed && styles.pressed]}
            >
              <Text style={styles.iconBtnText}>⚙︎</Text>
            </Pressable>
          </View>
        </View>

        {loadingShell ? <ConnectSkeleton /> : null}

        {auth.status === "unauthenticated" ? (
          <Text style={styles.help}>Sign in on Profile to use Connect.</Text>
        ) : null}

        {auth.status === "authenticated" && ghostOn ? <ConnectGhostState /> : null}

        {auth.status === "authenticated" && !ghostOn && (exited || !canSend) ? (
          <ConnectEmptyPresence onGoPresence={() => router.push("/(tabs)/presence")} />
        ) : null}

        {auth.status === "authenticated" && canSend && !ghostOn ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Nearby</Text>

            {discoverQuery.isLoading ? <ConnectSkeleton count={2} /> : null}
            {discoverQuery.isError ? (
              <ConnectErrorState
                title="Couldn’t load people here"
                onRetry={() => {
                  void discoverQuery.refetch();
                }}
              />
            ) : null}
            {!discoverQuery.isLoading &&
            !discoverQuery.isError &&
            (discoverQuery.data?.items ?? []).length === 0 ? (
              <ConnectEmptyNearby />
            ) : null}

            <View style={styles.stack}>
              {(discoverQuery.data?.items ?? []).map((user) => {
                const relation = relationForPerson({
                  userId: user.user_id,
                  pendingPeerIds,
                  connectedPeerIds,
                  localOps,
                  sendingUserId:
                    sendMutation.isPending && sendMutation.variables
                      ? sendMutation.variables.user.user_id
                      : null,
                });
                const actionLabel =
                  relation === "connected"
                    ? "Message"
                    : relation === "pending" || relation === "sending"
                      ? "Pending"
                      : "Send Calling Card";
                return (
                  <NearbyPersonCard
                    key={user.user_id}
                    person={user}
                    venueName={venueName}
                    selected={composerPerson?.user_id === user.user_id}
                    actionLabel={actionLabel}
                    actionPending={relation === "pending" || relation === "sending"}
                    statusHint={queueHintForRecipient(localOps, user.user_id)}
                    onSelect={() => {
                      if (relation === "available") {
                        openComposer(user);
                      }
                    }}
                    onPrimaryAction={() => {
                      if (relation === "connected") {
                        openMessageMutation.mutate(user.user_id);
                        return;
                      }
                      if (relation === "available") {
                        openComposer(user);
                      }
                    }}
                    onBlock={() => blockMutation.mutate(user.user_id)}
                  />
                );
              })}
            </View>
          </View>
        ) : null}

        {auth.status === "authenticated" && !ghostOn ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Incoming</Text>
            {inboxQuery.isLoading ? <ConnectSkeleton count={1} /> : null}
            {inboxQuery.isError ? (
              <ConnectErrorState
                title="Couldn’t load Calling Cards"
                onRetry={() => {
                  void inboxQuery.refetch();
                }}
              />
            ) : null}
            {!inboxQuery.isLoading && pendingInbox.length === 0 ? <ConnectEmptyPending /> : null}
            <View style={styles.stack}>
              {pendingInbox.map((card) => {
                const sender = peopleById.get(card.sender_user_id);
                return (
                  <CallingCardRow
                    key={card.id}
                    card={card}
                    nowMs={nowMs}
                    title={sender?.display_name ?? "Incoming Calling Card"}
                    handle={sender?.handle}
                    subtitle={
                      sender
                        ? `@${sender.handle}${venueName ? ` · ${venueName}` : ""}`
                        : venueName
                          ? `At ${venueName}`
                          : null
                    }
                    queueHint={queueHintForCard(localOps, card.id)}
                    busy={respondMutation.isPending}
                    onAccept={() => respondMutation.mutate({ card, decision: "accept" })}
                    onDecline={() => respondMutation.mutate({ card, decision: "decline" })}
                    onBlock={() => blockMutation.mutate(card.sender_user_id)}
                  />
                );
              })}
            </View>
          </View>
        ) : null}

        {auth.status === "authenticated" ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Sent</Text>
            {sentQuery.isLoading ? <ConnectSkeleton count={1} /> : null}
            {sentQuery.isError ? (
              <ConnectErrorState
                title="Couldn’t load sent cards"
                onRetry={() => {
                  void sentQuery.refetch();
                }}
              />
            ) : null}
            {!sentQuery.isLoading && pendingSent.length === 0 ? (
              <Text style={styles.muted}>No pending sent Calling Cards</Text>
            ) : null}
            <View style={styles.stack}>
              {pendingSent.map((card) => {
                const recipient = peopleById.get(card.recipient_user_id);
                return (
                  <CallingCardRow
                    key={card.id}
                    card={card}
                    nowMs={nowMs}
                    title={recipient?.display_name ?? "Sent Calling Card"}
                    handle={recipient?.handle}
                    subtitle={
                      recipient
                        ? `@${recipient.handle}`
                        : venueName
                          ? `At ${venueName}`
                          : null
                    }
                    queueHint={queueHintForCard(localOps, card.id)}
                    busy={cancelMutation.isPending}
                    onCancel={() => cancelMutation.mutate(card)}
                  />
                );
              })}
            </View>
          </View>
        ) : null}

        {auth.status === "authenticated" ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Connections</Text>
            {connections.length === 0 ? <ConnectEmptyConnections /> : null}
            <View style={styles.stack}>
              {connections.map((card) => {
                const peerId = otherPartyId(card, myId);
                const peer = peopleById.get(peerId);
                return (
                  <CallingCardRow
                    key={`accepted-${peerId}`}
                    card={card}
                    nowMs={nowMs}
                    title={peer?.display_name ?? "Connected"}
                    handle={peer?.handle}
                    subtitle={peer ? `@${peer.handle}` : venueName ? `At ${venueName}` : null}
                    showConnectionExpiry
                    busy={openMessageMutation.isPending}
                    onMessage={() => openMessageMutation.mutate(peerId)}
                  />
                );
              })}
            </View>
          </View>
        ) : null}

        {actionError ? (
          <Text style={styles.error} accessibilityLiveRegion="polite" testID="connect-action-error">
            {actionError}
          </Text>
        ) : null}

        <DeveloperDiagnostics
          operations={localOps}
          presenceState={presenceQuery.data?.state}
          socialEligible={presenceQuery.data?.social_features_enabled}
          ghostOn={ghostOn}
        />
      </ScrollView>

      <CallingCardComposerSheet
        key={composerPerson?.user_id ?? "composer-closed"}
        visible={composerPerson != null}
        person={composerPerson}
        venueName={venueName}
        submitting={sendMutation.isPending}
        submitError={composerError}
        onClose={() => {
          if (sendMutation.isPending) {
            return;
          }
          setComposerPerson(null);
          setComposerError(null);
        }}
        onSend={({ reasonCode, customMessage }) => {
          if (!composerPerson || sendMutation.isPending) {
            return;
          }
          setComposerError(null);
          sendMutation.mutate({
            user: composerPerson,
            reasonCode,
            customMessage,
          });
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: {
    paddingHorizontal: 20,
    paddingTop: 8,
    gap: 22,
  },
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  headerCopy: { flex: 1, gap: 4 },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 36,
  },
  context: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  headerActions: { flexDirection: "row", alignItems: "center", gap: 8 },
  headerBtn: {
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: 999,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
  },
  headerBtnText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 13,
  },
  iconBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  iconBtnText: { color: colors.textPrimary, fontSize: 18 },
  section: { gap: 12 },
  sectionTitle: {
    color: colors.gold,
    fontFamily: fontFamilies.geistBold,
    fontSize: 12,
    letterSpacing: 1.2,
  },
  stack: { gap: 12 },
  help: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
  },
  muted: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  error: {
    color: colors.danger,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  pressed: { opacity: 0.88 },
});
