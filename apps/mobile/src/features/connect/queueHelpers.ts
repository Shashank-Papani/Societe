/** Pure helpers for the Connect offline command queue (ADR 0013 / arch §17). */

export type QueueOperationType =
  | "calling_card.create"
  | "calling_card.respond"
  | "calling_card.cancel"
  | "message.send";

export type QueueTerminalState =
  | "queued"
  | "sending"
  | "acknowledged"
  | "server_confirmed"
  | "failed_retryable"
  | "failed_permanent"
  | "expired";

export type ConnectUiState =
  | "queued"
  | "sending"
  | "server_pending"
  | "delivered"
  | "accepted"
  | "declined"
  | "expired"
  | "cancelled"
  | "failed_retryable"
  | "failed_permanent";

export type ErrorCategory = "retryable" | "permanent" | "expired" | "success";

const FORBIDDEN_PAYLOAD_KEYS = new Set([
  "access_token",
  "refresh_token",
  "authorization",
  "token",
  "latitude",
  "longitude",
  "horizontal_accuracy_m",
  "location",
  "evidence",
]);

export function isOperationExpired(
  expiresAt: string | null | undefined,
  nowMs: number = Date.now(),
): boolean {
  if (!expiresAt) {
    return false;
  }
  const parsed = Date.parse(expiresAt);
  if (Number.isNaN(parsed)) {
    return false;
  }
  return parsed <= nowMs;
}

export function classifyHttpFailure(
  status: number | null,
  options: { timedOut?: boolean; networkError?: boolean } = {},
): ErrorCategory {
  if (options.timedOut || options.networkError) {
    return "retryable";
  }
  if (status == null) {
    return "retryable";
  }
  if (status === 429) {
    return "retryable";
  }
  if (status >= 500 && status <= 599) {
    return "retryable";
  }
  if (status >= 400 && status < 500) {
    return "permanent";
  }
  return "retryable";
}

/** Full jitter exponential backoff. Caps at ~5 minutes. Honors Retry-After when present. */
export function computeNextAttemptDelayMs(
  attempts: number,
  retryAfterSeconds: number | null = null,
): number {
  if (retryAfterSeconds != null && retryAfterSeconds >= 0) {
    return Math.min(retryAfterSeconds * 1000, 5 * 60_000);
  }
  const base = Math.min(1000 * 2 ** Math.max(0, attempts - 1), 5 * 60_000);
  return Math.floor(Math.random() * (base + 1));
}

export function sanitizeQueuePayload(payload: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(payload)) {
    const lower = key.toLowerCase();
    if (FORBIDDEN_PAYLOAD_KEYS.has(lower)) {
      continue;
    }
    if (value != null && typeof value === "object" && !Array.isArray(value)) {
      out[key] = sanitizeQueuePayload(value as Record<string, unknown>);
      continue;
    }
    out[key] = value;
  }
  return out;
}

export function serializeQueuePayload(payload: Record<string, unknown>): string {
  return JSON.stringify(sanitizeQueuePayload(payload));
}

export function parseQueuePayload(payloadJson: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(payloadJson);
  if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Invalid queue payload JSON");
  }
  return sanitizeQueuePayload(parsed as Record<string, unknown>);
}

/**
 * True when the authoritative card status already matches the queued respond
 * decision (accept→accepted, decline→declined). Used to clear stale queue rows
 * after a network failure that occurred after the server committed.
 */
export function respondDecisionMatchesTerminalStatus(
  decision: string,
  status: string,
): boolean {
  if (decision === "accept") {
    return status === "accepted";
  }
  if (decision === "decline") {
    return status === "declined";
  }
  return false;
}

export type ReconcileQueueOp = {
  id: string;
  operationType: string;
  payloadJson: string;
  state: string;
};

export type ReconcileCard = {
  id: string;
  status: string;
};

/**
 * Returns ids of active ``calling_card.respond`` ops that should be acknowledged
 * because inbox/sent already shows a matching terminal status.
 */
export function findRespondOperationsToAcknowledge(
  operations: ReconcileQueueOp[],
  cards: ReconcileCard[],
): string[] {
  const statusById = new Map(cards.map((card) => [card.id, card.status]));
  const activeStates = new Set(["queued", "sending", "failed_retryable"]);
  const ids: string[] = [];

  for (const op of operations) {
    if (op.operationType !== "calling_card.respond") {
      continue;
    }
    if (!activeStates.has(op.state)) {
      continue;
    }
    let payload: Record<string, unknown>;
    try {
      payload = parseQueuePayload(op.payloadJson);
    } catch {
      continue;
    }
    const cardId = String(payload.calling_card_id ?? "");
    const decision = String(payload.decision ?? "");
    const status = statusById.get(cardId);
    if (!status) {
      continue;
    }
    if (respondDecisionMatchesTerminalStatus(decision, status)) {
      ids.push(op.id);
    }
  }
  return ids;
}

export function mapServerCardStatusToUi(status: string): ConnectUiState {
  switch (status) {
    case "pending":
      return "delivered";
    case "accepted":
      return "accepted";
    case "declined":
      return "declined";
    case "expired":
      return "expired";
    case "cancelled":
      return "cancelled";
    case "blocked":
      return "failed_permanent";
    default:
      return "server_pending";
  }
}

export function uiLabelForConnectState(state: ConnectUiState): string {
  switch (state) {
    case "queued":
    case "sending":
      return "Sending…";
    case "server_pending":
      return "Pending confirmation";
    case "delivered":
      return "Delivered · awaiting reply";
    case "accepted":
      return "Accepted";
    case "declined":
      return "Declined";
    case "expired":
      return "Expired";
    case "cancelled":
      return "Cancelled";
    case "failed_retryable":
      return "Failed · will retry";
    case "failed_permanent":
      return "Failed";
    default:
      return state;
  }
}

export function formatExpiryCountdown(
  expiresAt: string | null | undefined,
  nowMs: number = Date.now(),
): string | null {
  if (!expiresAt) {
    return null;
  }
  const end = Date.parse(expiresAt);
  if (Number.isNaN(end)) {
    return null;
  }
  const remaining = end - nowMs;
  if (remaining <= 0) {
    return "Expired";
  }
  const totalSec = Math.floor(remaining / 1000);
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m left`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s left`;
  }
  return `${seconds}s left`;
}

const REASON_LABELS: Record<string, string> = {
  love_the_dance_moves: "Love the dance moves",
  great_conversation: "Great conversation",
  nice_style: "Nice style",
  shared_vibe: "Shared vibe",
  say_hello: "Say hello",
};

export function reasonCodeLabel(code: string): string {
  const normalized = code.trim().toLowerCase();
  if (REASON_LABELS[normalized]) {
    return REASON_LABELS[normalized];
  }
  return normalized
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
