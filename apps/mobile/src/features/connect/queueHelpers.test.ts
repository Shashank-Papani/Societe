import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  classifyHttpFailure,
  computeNextAttemptDelayMs,
  formatExpiryCountdown,
  isOperationExpired,
  mapServerCardStatusToUi,
  parseQueuePayload,
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
