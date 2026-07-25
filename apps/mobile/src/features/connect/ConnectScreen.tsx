import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Constants from "expo-constants";
import { useEffect, useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { REALTIME_URL } from "@/api/client";
import { getLiveAccessToken, useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";
import {
  blockUser,
  CALLING_CARD_REASON_CODES,
  fetchCallingCardInbox,
  fetchCallingCardSent,
  fetchDiscoverableUsers,
  newIdempotencyKey,
  type CallingCardSummary,
  type DiscoverableUser,
} from "@/features/connect/api";
import {
  enqueueCancelCallingCard,
  enqueueCreateCallingCard,
  enqueueRespondCallingCard,
  flushOfflineQueue,
  listActiveQueuedOperations,
  type QueuedOperation,
} from "@/features/connect/offlineQueue";
import {
  formatExpiryCountdown,
  mapServerCardStatusToUi,
  reasonCodeLabel,
  uiLabelForConnectState,
  type ConnectUiState,
} from "@/features/connect/queueHelpers";
import { fetchPresenceMe } from "@/features/presence/api";

const INBOX_POLL_MS = 12_000;
const QUEUE_FLUSH_MS = 8_000;

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
      return "delivered";
    default:
      return "queued";
  }
}

export function ConnectScreen() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [selectedUser, setSelectedUser] = useState<DiscoverableUser | null>(null);
  const [reasonCode, setReasonCode] = useState<string>(CALLING_CARD_REASON_CODES[0]);
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
    const token = getLiveAccessToken();
    const extra = Constants.expoConfig?.extra as { realtimeUrl?: string } | undefined;
    const base = extra?.realtimeUrl ?? REALTIME_URL;
    if (!token || !base || typeof WebSocket === "undefined") {
      return;
    }

    const separator = base.includes("?") ? "&" : "?";
    const url = `${base}${separator}access_token=${encodeURIComponent(token)}`;

    let closed = false;
    let socket: WebSocket | null = null;
    try {
      socket = new WebSocket(url);
    } catch {
      return;
    }

    socket.onmessage = () => {
      if (!closed) {
        void queryClient.invalidateQueries({ queryKey: ["connect", "inbox"] });
        void queryClient.invalidateQueries({ queryKey: ["connect", "sent"] });
      }
    };

    return () => {
      closed = true;
      socket?.close();
    };
  }, [auth.status, queryClient]);

  const invalidateConnect = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["connect"] }),
      queryClient.invalidateQueries({ queryKey: ["presence", "me"] }),
    ]);
  };

  const sendMutation = useMutation({
    mutationFn: async () => {
      if (!selectedUser) {
        throw new Error("Pick someone nearby first.");
      }
      const key = newIdempotencyKey();
      await enqueueCreateCallingCard({
        recipientUserId: selectedUser.user_id,
        reasonCode,
        idempotencyKey: key,
      });
      await flushOfflineQueue();
    },
    onSuccess: async () => {
      setActionError(null);
      setSelectedUser(null);
      await invalidateConnect();
    },
    onError: (error: Error) => setActionError(error.message),
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
    onError: (error: Error) => setActionError(error.message),
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
    onError: (error: Error) => setActionError(error.message),
  });

  const blockMutation = useMutation({
    mutationFn: (userId: string) => blockUser(userId, "harassment"),
    onSuccess: async () => {
      setActionError(null);
      await invalidateConnect();
    },
    onError: (error: Error) => setActionError(error.message),
  });

  const venueName = presenceQuery.data?.venue?.name ?? null;
  const pendingInbox = (inboxQuery.data?.items ?? []).filter((c) => c.status === "pending");
  const sentItems = sentQuery.data?.items ?? [];
  const localOps = queueQuery.data ?? [];

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.title}>Connect</Text>
      <Text style={styles.subtitle}>
        Same-venue Calling Cards · server-authoritative eligibility
      </Text>

      {auth.status === "initializing" || presenceQuery.isLoading ? (
        <ActivityIndicator color="#9aa6bf" />
      ) : null}

      {auth.status === "unauthenticated" ? (
        <Text style={styles.help}>Sign in on Profile to use Connect.</Text>
      ) : null}

      {auth.status === "authenticated" ? (
        <View style={styles.card}>
          <Text style={styles.section}>Presence gate</Text>
          <Text style={styles.meta}>State: {presenceQuery.data?.state ?? "—"}</Text>
          <Text style={styles.meta}>Venue: {venueName ?? "—"}</Text>
          <Text style={styles.meta}>
            Social eligible: {presenceQuery.data?.social_features_enabled ? "yes" : "no"}
          </Text>
          <Text style={styles.meta}>Ghost Mode: {ghostOn ? "on" : "off"}</Text>
        </View>
      ) : null}

      {auth.status === "authenticated" && ghostOn ? (
        <Text style={styles.help}>
          Ghost Mode is on. You can browse Discover/Experience, but Calling Cards are disabled
          until Ghost Mode is off and presence is re-verified.
        </Text>
      ) : null}

      {auth.status === "authenticated" && !ghostOn && exited ? (
        <Text style={styles.help}>
          You are not verified at a venue. Submit presence on the Presence tab before sending or
          accepting Calling Cards.
        </Text>
      ) : null}

      {auth.status === "authenticated" && !ghostOn && !canSend && !exited ? (
        <Text style={styles.help}>
          Social features are not enabled for this presence lease yet. Refresh presence or wait for
          verification to complete.
        </Text>
      ) : null}

      {auth.status === "authenticated" && canSend && !ghostOn ? (
        <View style={styles.card}>
          <Text style={styles.section}>Nearby · {venueName}</Text>
          {discoverQuery.isLoading ? <ActivityIndicator color="#9aa6bf" /> : null}
          {discoverQuery.error ? (
            <Text style={styles.error}>{(discoverQuery.error as Error).message}</Text>
          ) : null}
          {(discoverQuery.data?.items ?? []).length === 0 && !discoverQuery.isLoading ? (
            <Text style={styles.help}>No discoverable people here right now.</Text>
          ) : null}
          {(discoverQuery.data?.items ?? []).map((user) => {
            const selected = selectedUser?.user_id === user.user_id;
            return (
              <Pressable
                key={user.user_id}
                style={[styles.rowItem, selected && styles.rowItemSelected]}
                onPress={() => setSelectedUser(user)}
              >
                <Text style={styles.author}>{user.display_name}</Text>
                <Text style={styles.meta}>@{user.handle}</Text>
                <Pressable
                  style={styles.inlineLink}
                  onPress={() => blockMutation.mutate(user.user_id)}
                >
                  <Text style={styles.reportText}>Block</Text>
                </Pressable>
              </Pressable>
            );
          })}

          {selectedUser ? (
            <View style={styles.compose}>
              <Text style={styles.meta}>
                Send to {selectedUser.display_name} · reason
              </Text>
              {CALLING_CARD_REASON_CODES.map((code) => (
                <Pressable
                  key={code}
                  style={[styles.chip, reasonCode === code && styles.chipSelected]}
                  onPress={() => setReasonCode(code)}
                >
                  <Text style={styles.chipText}>{reasonCodeLabel(code)}</Text>
                </Pressable>
              ))}
              <Pressable
                style={[styles.button, sendMutation.isPending && styles.buttonDisabled]}
                disabled={sendMutation.isPending}
                onPress={() => sendMutation.mutate()}
              >
                <Text style={styles.buttonText}>
                  {sendMutation.isPending ? "Queueing…" : "Send Calling Card"}
                </Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      ) : null}

      {localOps.length > 0 ? (
        <View style={styles.card}>
          <Text style={styles.section}>Outbound queue</Text>
          {localOps.map((op) => {
            const ui = localOpUiState(op);
            return (
              <View key={op.id} style={styles.rowItem}>
                <Text style={styles.author}>{op.operationType}</Text>
                <Text style={styles.meta}>{uiLabelForConnectState(ui)}</Text>
                {op.lastErrorCode ? (
                  <Text style={styles.error}>{op.lastErrorCode}</Text>
                ) : null}
              </View>
            );
          })}
        </View>
      ) : null}

      <Text style={styles.section}>Inbox</Text>
      {inboxQuery.isLoading ? <ActivityIndicator color="#9aa6bf" /> : null}
      {inboxQuery.error ? (
        <Text style={styles.error}>{(inboxQuery.error as Error).message}</Text>
      ) : null}
      {pendingInbox.length === 0 && !inboxQuery.isLoading ? (
        <Text style={styles.help}>No pending Calling Cards.</Text>
      ) : null}
      {pendingInbox.map((card) => (
        <CardRow
          key={card.id}
          card={card}
          nowMs={nowMs}
          actions={
            <View style={styles.actions}>
              <Pressable
                style={styles.button}
                onPress={() => respondMutation.mutate({ card, decision: "accept" })}
                disabled={respondMutation.isPending}
              >
                <Text style={styles.buttonText}>Accept</Text>
              </Pressable>
              <Pressable
                style={styles.buttonSecondary}
                onPress={() => respondMutation.mutate({ card, decision: "decline" })}
                disabled={respondMutation.isPending}
              >
                <Text style={styles.buttonSecondaryText}>Decline</Text>
              </Pressable>
              <Pressable
                style={styles.inlineLink}
                onPress={() => blockMutation.mutate(card.sender_user_id)}
              >
                <Text style={styles.reportText}>Block sender</Text>
              </Pressable>
            </View>
          }
        />
      ))}

      <Text style={styles.section}>Sent</Text>
      <Text style={styles.help}>
        Only cards confirmed by the server appear here. Local queue items stay above until ack.
      </Text>
      {sentQuery.isLoading ? <ActivityIndicator color="#9aa6bf" /> : null}
      {sentQuery.error ? (
        <Text style={styles.error}>{(sentQuery.error as Error).message}</Text>
      ) : null}
      {sentItems.length === 0 && !sentQuery.isLoading ? (
        <Text style={styles.help}>No server-confirmed sent cards yet.</Text>
      ) : null}
      {sentItems.map((card) => (
        <CardRow
          key={card.id}
          card={card}
          nowMs={nowMs}
          actions={
            card.status === "pending" ? (
              <Pressable
                style={styles.buttonSecondary}
                onPress={() => cancelMutation.mutate(card)}
                disabled={cancelMutation.isPending}
              >
                <Text style={styles.buttonSecondaryText}>Cancel</Text>
              </Pressable>
            ) : null
          }
        />
      ))}

      {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
    </ScrollView>
  );
}

function CardRow({
  card,
  nowMs,
  actions,
}: {
  card: CallingCardSummary;
  nowMs: number;
  actions?: ReactNode;
}) {
  const ui = mapServerCardStatusToUi(card.status);
  const countdown = formatExpiryCountdown(card.expires_at, nowMs);
  return (
    <View style={styles.vibe}>
      <Text style={styles.author}>{uiLabelForConnectState(ui)}</Text>
      <Text style={styles.meta}>
        {card.reason_code ? reasonCodeLabel(card.reason_code) : "No reason"} · {card.status}
      </Text>
      {countdown ? <Text style={styles.meta}>{countdown}</Text> : null}
      {actions}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b1220" },
  content: { padding: 20, gap: 12, paddingBottom: 64 },
  brand: { color: "#f5f7fb", fontSize: 28, fontWeight: "700", letterSpacing: 0.4 },
  title: { color: "#f5f7fb", fontSize: 22, fontWeight: "600" },
  subtitle: { color: "#9aa6bf", marginBottom: 8 },
  section: { color: "#f5f7fb", fontSize: 16, fontWeight: "600", marginTop: 8 },
  help: { color: "#9aa6bf", lineHeight: 20 },
  error: { color: "#f87171" },
  card: {
    gap: 8,
    padding: 14,
    borderRadius: 12,
    backgroundColor: "#121a2b",
    borderColor: "#1e293b",
    borderWidth: 1,
  },
  meta: { color: "#9aa6bf", fontSize: 13 },
  author: { color: "#f5f7fb", fontWeight: "600" },
  rowItem: {
    gap: 4,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#1e293b",
  },
  rowItemSelected: {
    backgroundColor: "#1a2740",
    borderRadius: 8,
    paddingHorizontal: 8,
  },
  compose: { gap: 8, marginTop: 8 },
  chip: {
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 10,
  },
  chipSelected: {
    borderColor: "#2563eb",
    backgroundColor: "#172554",
  },
  chipText: { color: "#cbd5e1" },
  button: {
    backgroundColor: "#2563eb",
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  buttonSecondary: {
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#334155",
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: "#f5f7fb", fontWeight: "600" },
  buttonSecondaryText: { color: "#cbd5e1", fontWeight: "500" },
  actions: { gap: 8, marginTop: 8 },
  inlineLink: { alignSelf: "flex-start", paddingVertical: 4 },
  reportText: { color: "#f87171", fontSize: 13 },
  vibe: {
    gap: 6,
    paddingBottom: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#1e293b",
  },
});
