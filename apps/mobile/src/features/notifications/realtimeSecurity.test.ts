import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  assertSafeNotificationsWsUrl,
  buildAuthenticateFrame,
  notificationsWsUrlFromApiBase,
} from "./realtimeHelpers.ts";
import {
  clearHandledNotificationResponses,
  markNotificationResponseHandled,
  wasNotificationResponseHandled,
} from "./notificationResponseDedupe.ts";
import { realtimeBackoffMs } from "./notificationHelpers.ts";

describe("Notifications realtime security", () => {
  it("builds authenticate frame as first message shape", () => {
    const frame = buildAuthenticateFrame("t".repeat(32));
    assert.equal(frame.type, "authenticate");
    assert.equal(frame.ticket.length, 32);
  });

  it("builds websocket URL without secrets", () => {
    const url = notificationsWsUrlFromApiBase("http://localhost:8000");
    assert.equal(url, "ws://localhost:8000/v1/realtime/notifications");
    assert.equal(assertSafeNotificationsWsUrl(url), true);
  });

  it("rejects websocket URLs that embed ticket or access_token", () => {
    assert.equal(
      assertSafeNotificationsWsUrl("ws://localhost:8000/v1/realtime/notifications"),
      true,
    );
    assert.equal(
      assertSafeNotificationsWsUrl(
        "ws://localhost:8000/v1/realtime/notifications?ticket=secret",
      ),
      false,
    );
    assert.equal(
      assertSafeNotificationsWsUrl(
        "ws://localhost:8000/v1/realtime/notifications?access_token=secret",
      ),
      false,
    );
  });

  it("bounds reconnect backoff", () => {
    for (let attempt = 1; attempt <= 10; attempt += 1) {
      const delay = realtimeBackoffMs(attempt);
      assert.ok(delay >= 0);
      assert.ok(delay <= 30_000);
    }
  });
});

describe("Notification response dedupe", () => {
  it("marks and clears handled responses for account isolation", () => {
    clearHandledNotificationResponses();
    markNotificationResponseHandled("abc");
    assert.equal(wasNotificationResponseHandled("abc"), true);
    clearHandledNotificationResponses();
    assert.equal(wasNotificationResponseHandled("abc"), false);
  });
});
