import * as Crypto from "expo-crypto";
import * as SQLite from "expo-sqlite";

import { ApiError } from "@/api/client";
import {
  cancelCallingCard,
  createCallingCard,
  respondCallingCard,
  type ResponseDecision,
  type ShareScope,
} from "@/features/connect/api";
import {
  classifyHttpFailure,
  computeNextAttemptDelayMs,
  isOperationExpired,
  parseQueuePayload,
  serializeQueuePayload,
  type QueueOperationType,
  type QueueTerminalState,
} from "@/features/connect/queueHelpers";

const DB_NAME = "societe_connect_queue.db";
const MAX_ATTEMPTS = 12;

export type QueuedOperation = {
  id: string;
  operationType: QueueOperationType;
  payloadJson: string;
  idempotencyKey: string;
  priority: number;
  state: QueueTerminalState;
  attempts: number;
  nextAttemptAt: string;
  createdAt: string;
  lastAttemptAt: string | null;
  lastErrorCode: string | null;
  expiresAt: string | null;
  serverCardId: string | null;
};

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

async function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) {
    dbPromise = (async () => {
      const db = await SQLite.openDatabaseAsync(DB_NAME);
      await db.execAsync(`
        CREATE TABLE IF NOT EXISTS operation_queue (
          id TEXT PRIMARY KEY NOT NULL,
          operation_type TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          priority INTEGER NOT NULL,
          state TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          last_attempt_at TEXT,
          last_error_code TEXT,
          expires_at TEXT,
          server_card_id TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_operation_idempotency
          ON operation_queue(idempotency_key);
      `);
      return db;
    })();
  }
  return dbPromise;
}

function priorityFor(type: QueueOperationType): number {
  switch (type) {
    case "calling_card.respond":
      return 1;
    case "calling_card.create":
      return 2;
    case "calling_card.cancel":
      return 3;
    default:
      return 9;
  }
}

function rowToOp(row: Record<string, unknown>): QueuedOperation {
  return {
    id: String(row.id),
    operationType: row.operation_type as QueueOperationType,
    payloadJson: String(row.payload_json),
    idempotencyKey: String(row.idempotency_key),
    priority: Number(row.priority),
    state: row.state as QueueTerminalState,
    attempts: Number(row.attempts),
    nextAttemptAt: String(row.next_attempt_at),
    createdAt: String(row.created_at),
    lastAttemptAt: row.last_attempt_at == null ? null : String(row.last_attempt_at),
    lastErrorCode: row.last_error_code == null ? null : String(row.last_error_code),
    expiresAt: row.expires_at == null ? null : String(row.expires_at),
    serverCardId: row.server_card_id == null ? null : String(row.server_card_id),
  };
}

async function insertOperation(input: {
  operationType: QueueOperationType;
  payload: Record<string, unknown>;
  idempotencyKey: string;
  expiresAt?: string | null;
}): Promise<QueuedOperation> {
  const db = await getDb();
  const now = new Date().toISOString();
  const op: QueuedOperation = {
    id: Crypto.randomUUID(),
    operationType: input.operationType,
    payloadJson: serializeQueuePayload(input.payload),
    idempotencyKey: input.idempotencyKey,
    priority: priorityFor(input.operationType),
    state: "queued",
    attempts: 0,
    nextAttemptAt: now,
    createdAt: now,
    lastAttemptAt: null,
    lastErrorCode: null,
    expiresAt: input.expiresAt ?? null,
    serverCardId: null,
  };

  await db.runAsync(
    `INSERT INTO operation_queue (
      id, operation_type, payload_json, idempotency_key, priority, state,
      attempts, next_attempt_at, created_at, last_attempt_at, last_error_code,
      expires_at, server_card_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    op.id,
    op.operationType,
    op.payloadJson,
    op.idempotencyKey,
    op.priority,
    op.state,
    op.attempts,
    op.nextAttemptAt,
    op.createdAt,
    op.lastAttemptAt,
    op.lastErrorCode,
    op.expiresAt,
    op.serverCardId,
  );

  return op;
}

export async function enqueueCreateCallingCard(input: {
  recipientUserId: string;
  reasonCode?: string | null;
  reasonText?: string | null;
  idempotencyKey: string;
  /** Business expiry hint; skipped after this timestamp. */
  expiresAt?: string | null;
}): Promise<QueuedOperation> {
  return insertOperation({
    operationType: "calling_card.create",
    idempotencyKey: input.idempotencyKey,
    expiresAt: input.expiresAt ?? null,
    payload: {
      recipient_user_id: input.recipientUserId,
      reason_code: input.reasonCode ?? null,
      reason_text: input.reasonText ?? null,
    },
  });
}

export async function enqueueRespondCallingCard(input: {
  callingCardId: string;
  decision: ResponseDecision;
  action?: "share_info" | "make_move" | "accept_only" | null;
  shareScopes?: ShareScope[];
  idempotencyKey: string;
  expiresAt?: string | null;
}): Promise<QueuedOperation> {
  return insertOperation({
    operationType: "calling_card.respond",
    idempotencyKey: input.idempotencyKey,
    expiresAt: input.expiresAt ?? null,
    payload: {
      calling_card_id: input.callingCardId,
      decision: input.decision,
      action: input.action ?? null,
      share_scopes: input.shareScopes ?? [],
    },
  });
}

export async function enqueueCancelCallingCard(input: {
  callingCardId: string;
  idempotencyKey: string;
  expiresAt?: string | null;
}): Promise<QueuedOperation> {
  return insertOperation({
    operationType: "calling_card.cancel",
    idempotencyKey: input.idempotencyKey,
    expiresAt: input.expiresAt ?? null,
    payload: {
      calling_card_id: input.callingCardId,
    },
  });
}

export async function listActiveQueuedOperations(): Promise<QueuedOperation[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<Record<string, unknown>>(
    `SELECT * FROM operation_queue
     WHERE state IN ('queued', 'sending', 'failed_retryable')
     ORDER BY priority ASC, created_at ASC`,
  );
  return rows.map(rowToOp);
}

export async function listAllQueuedOperations(): Promise<QueuedOperation[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<Record<string, unknown>>(
    `SELECT * FROM operation_queue ORDER BY created_at DESC LIMIT 50`,
  );
  return rows.map(rowToOp);
}

async function markState(
  id: string,
  patch: {
    state: QueueTerminalState;
    attempts?: number;
    nextAttemptAt?: string;
    lastAttemptAt?: string | null;
    lastErrorCode?: string | null;
    clearLastError?: boolean;
    serverCardId?: string | null;
    expiresAt?: string | null;
  },
): Promise<void> {
  const db = await getDb();
  const current = await db.getFirstAsync<Record<string, unknown>>(
    `SELECT * FROM operation_queue WHERE id = ?`,
    id,
  );
  if (!current) {
    return;
  }
  await db.runAsync(
    `UPDATE operation_queue SET
      state = ?,
      attempts = ?,
      next_attempt_at = ?,
      last_attempt_at = ?,
      last_error_code = ?,
      server_card_id = ?,
      expires_at = ?
     WHERE id = ?`,
    patch.state,
    patch.attempts ?? Number(current.attempts),
    patch.nextAttemptAt ?? String(current.next_attempt_at),
    patch.lastAttemptAt !== undefined
      ? patch.lastAttemptAt
      : (current.last_attempt_at as string | null),
    patch.clearLastError
      ? null
      : patch.lastErrorCode !== undefined
        ? patch.lastErrorCode
        : (current.last_error_code as string | null),
    patch.serverCardId !== undefined
      ? patch.serverCardId
      : (current.server_card_id as string | null),
    patch.expiresAt !== undefined ? patch.expiresAt : (current.expires_at as string | null),
    id,
  );
}

async function executeOperation(op: QueuedOperation): Promise<{
  serverCardId: string | null;
  expiresAt: string | null;
}> {
  const payload = parseQueuePayload(op.payloadJson);

  if (op.operationType === "calling_card.create") {
    const result = await createCallingCard(
      {
        recipientUserId: String(payload.recipient_user_id),
        reasonCode: (payload.reason_code as string | null | undefined) ?? null,
        reasonText: (payload.reason_text as string | null | undefined) ?? null,
      },
      op.idempotencyKey,
    );
    return { serverCardId: result.id, expiresAt: result.expires_at };
  }

  if (op.operationType === "calling_card.respond") {
    const result = await respondCallingCard(
      String(payload.calling_card_id),
      {
        decision: payload.decision as ResponseDecision,
        action:
          (payload.action as "share_info" | "make_move" | "accept_only" | null | undefined) ??
          null,
        shareScopes: (payload.share_scopes as ShareScope[] | undefined) ?? [],
      },
      op.idempotencyKey,
    );
    return {
      serverCardId: result.card.id,
      expiresAt: result.card.expires_at,
    };
  }

  if (op.operationType === "calling_card.cancel") {
    const result = await cancelCallingCard(
      String(payload.calling_card_id),
      op.idempotencyKey,
    );
    return { serverCardId: result.id, expiresAt: result.expires_at };
  }

  throw new Error(`Unsupported operation type: ${op.operationType}`);
}

function failureMeta(error: unknown): {
  category: ReturnType<typeof classifyHttpFailure>;
  code: string;
  retryAfterSeconds: number | null;
} {
  if (error instanceof ApiError) {
    return {
      category: classifyHttpFailure(error.status),
      code: error.code,
      retryAfterSeconds: error.retryAfterSeconds,
    };
  }
  const message = error instanceof Error ? error.message : String(error);
  const timedOut = /timeout|timed out|aborted/i.test(message);
  const networkError = /network|fetch failed|offline|failed to fetch/i.test(message);
  return {
    category: classifyHttpFailure(null, { timedOut, networkError: networkError || !timedOut }),
    code: timedOut ? "TIMEOUT" : "NETWORK",
    retryAfterSeconds: null,
  };
}

export type FlushResult = {
  processed: number;
  acknowledged: number;
  failedRetryable: number;
  failedPermanent: number;
  expired: number;
};

/** Flush due queue items. Preserves original idempotency keys. Skips expired ops. */
export async function flushOfflineQueue(nowMs: number = Date.now()): Promise<FlushResult> {
  const db = await getDb();
  const nowIso = new Date(nowMs).toISOString();
  const rows = await db.getAllAsync<Record<string, unknown>>(
    `SELECT * FROM operation_queue
     WHERE state IN ('queued', 'failed_retryable')
       AND next_attempt_at <= ?
     ORDER BY priority ASC, created_at ASC
     LIMIT 20`,
    nowIso,
  );

  const result: FlushResult = {
    processed: 0,
    acknowledged: 0,
    failedRetryable: 0,
    failedPermanent: 0,
    expired: 0,
  };

  for (const row of rows) {
    const op = rowToOp(row);
    result.processed += 1;

    if (isOperationExpired(op.expiresAt, nowMs)) {
      await markState(op.id, {
        state: "expired",
        lastAttemptAt: nowIso,
        lastErrorCode: "EXPIRED",
      });
      result.expired += 1;
      continue;
    }

    await markState(op.id, { state: "sending", lastAttemptAt: nowIso });

    try {
      const executed = await executeOperation(op);
      await markState(op.id, {
        state: "acknowledged",
        attempts: op.attempts + 1,
        lastAttemptAt: nowIso,
        clearLastError: true,
        serverCardId: executed.serverCardId,
        expiresAt: executed.expiresAt,
      });
      result.acknowledged += 1;
    } catch (error) {
      const meta = failureMeta(error);
      const attempts = op.attempts + 1;

      if (meta.category === "permanent" || attempts >= MAX_ATTEMPTS) {
        await markState(op.id, {
          state: "failed_permanent",
          attempts,
          lastAttemptAt: nowIso,
          lastErrorCode: meta.code,
        });
        result.failedPermanent += 1;
        continue;
      }

      const delay = computeNextAttemptDelayMs(attempts, meta.retryAfterSeconds);
      await markState(op.id, {
        state: "failed_retryable",
        attempts,
        lastAttemptAt: nowIso,
        lastErrorCode: meta.code,
        nextAttemptAt: new Date(nowMs + delay).toISOString(),
      });
      result.failedRetryable += 1;
    }
  }

  return result;
}
