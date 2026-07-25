import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  classifyHttpFailure,
  computeNextAttemptDelayMs,
  findRespondOperationsToAcknowledge,
  formatExpiryCountdown,
  isOperationExpired,
  mapServerCardStatusToUi,
  parseQueuePayload,
  respondDecisionMatchesTerminalStatus,
  serializeQueuePayload,
  uiLabelForConnectState,
} from "./queueHelpers.ts";

describe("serializeQueuePayload", () => {
  it("strips tokens and location fields", () => {
    const json = serializeQueuePayload({
      recipient_user_id: "u1",
      access_token: "secret",
      latitude: 40.7,
      location: { latitude: 1, longitude: 2 },
      reason_code: "say_hello",
    });
    const parsed = JSON.parse(json) as Record<string, unknown>;
    assert.equal(parsed.recipient_user_id, "u1");
    assert.equal(parsed.reason_code, "say_hello");
    assert.equal("access_token" in parsed, false);
    assert.equal("latitude" in parsed, false);
    assert.equal("location" in parsed, false);
  });

  it("round-trips via parseQueuePayload", () => {
    const json = serializeQueuePayload({
      calling_card_id: "c1",
      decision: "accept",
      share_scopes: ["instagram"],
    });
    const parsed = parseQueuePayload(json);
    assert.equal(parsed.calling_card_id, "c1");
    assert.deepEqual(parsed.share_scopes, ["instagram"]);
  });
});

describe("classifyHttpFailure", () => {
  it("retries timeout, 429, and 5xx", () => {
    assert.equal(classifyHttpFailure(null, { timedOut: true }), "retryable");
    assert.equal(classifyHttpFailure(429), "retryable");
    assert.equal(classifyHttpFailure(503), "retryable");
  });

  it("marks permanent 4xx as permanent", () => {
    assert.equal(classifyHttpFailure(400), "permanent");
    assert.equal(classifyHttpFailure(403), "permanent");
    assert.equal(classifyHttpFailure(404), "permanent");
  });
});

describe("isOperationExpired", () => {
  it("skips ops past expires_at", () => {
    assert.equal(isOperationExpired("2020-01-01T00:00:00.000Z", Date.parse("2024-01-01")), true);
    assert.equal(isOperationExpired("2099-01-01T00:00:00.000Z", Date.parse("2024-01-01")), false);
    assert.equal(isOperationExpired(null), false);
  });
});

describe("computeNextAttemptDelayMs", () => {
  it("honors Retry-After seconds", () => {
    assert.equal(computeNextAttemptDelayMs(1, 30), 30_000);
  });

  it("stays within backoff cap", () => {
    const delay = computeNextAttemptDelayMs(20, null);
    assert.ok(delay >= 0 && delay <= 5 * 60_000);
  });
});

describe("mapServerCardStatusToUi", () => {
  it("never maps pending to a Sent-before-confirm label", () => {
    assert.equal(mapServerCardStatusToUi("pending"), "delivered");
    assert.equal(uiLabelForConnectState("queued"), "Sending…");
    assert.equal(uiLabelForConnectState("sending"), "Sending…");
    assert.notEqual(uiLabelForConnectState("queued"), "Sent");
  });
});

describe("formatExpiryCountdown", () => {
  it("formats remaining time", () => {
    const now = Date.parse("2024-01-01T00:00:00.000Z");
    const label = formatExpiryCountdown("2024-01-01T00:05:30.000Z", now);
    assert.equal(label, "5m 30s left");
  });
});

describe("respond queue reconciliation after NETWORK following server commit", () => {
  it("matches accept→accepted and decline→declined only", () => {
    assert.equal(respondDecisionMatchesTerminalStatus("accept", "accepted"), true);
    assert.equal(respondDecisionMatchesTerminalStatus("decline", "declined"), true);
    assert.equal(respondDecisionMatchesTerminalStatus("accept", "pending"), false);
    assert.equal(respondDecisionMatchesTerminalStatus("accept", "declined"), false);
    assert.equal(respondDecisionMatchesTerminalStatus("decline", "accepted"), false);
  });

  it("clears failed_retryable NETWORK respond when authoritative card is accepted", () => {
    const cardId = "card-accepted-1";
    const staleRespond = {
      id: "op-1",
      operationType: "calling_card.respond",
      state: "failed_retryable",
      payloadJson: serializeQueuePayload({
        calling_card_id: cardId,
        decision: "accept",
        action: "accept_only",
        share_scopes: [],
      }),
    };
    const unrelatedCreate = {
      id: "op-2",
      operationType: "calling_card.create",
      state: "failed_retryable",
      payloadJson: serializeQueuePayload({
        recipient_user_id: "u2",
        reason_code: "say_hello",
      }),
    };
    const pendingRespond = {
      id: "op-3",
      operationType: "calling_card.respond",
      state: "failed_retryable",
      payloadJson: serializeQueuePayload({
        calling_card_id: "card-still-pending",
        decision: "accept",
        action: "accept_only",
        share_scopes: [],
      }),
    };

    const toAck = findRespondOperationsToAcknowledge(
      [staleRespond, unrelatedCreate, pendingRespond],
      [
        { id: cardId, status: "accepted" },
        { id: "card-still-pending", status: "pending" },
      ],
    );

    assert.deepEqual(toAck, ["op-1"]);
  });

  it("does not acknowledge when decision and status disagree", () => {
    const toAck = findRespondOperationsToAcknowledge(
      [
        {
          id: "op-decline",
          operationType: "calling_card.respond",
          state: "queued",
          payloadJson: serializeQueuePayload({
            calling_card_id: "c1",
            decision: "decline",
          }),
        },
      ],
      [{ id: "c1", status: "accepted" }],
    );
    assert.deepEqual(toAck, []);
  });
});
