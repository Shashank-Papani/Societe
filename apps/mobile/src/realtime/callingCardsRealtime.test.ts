import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  assertSafeCallingCardsWsUrl,
  buildCallingCardsAuthenticateFrame,
  callingCardsWsUrlFromApiBase,
} from "./urlHelpers.ts";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function read(rel: string): string {
  return readFileSync(path.join(mobileRoot, rel), "utf8");
}

describe("Calling Card realtime security", () => {
  it("builds websocket URL without secrets", () => {
    const url = callingCardsWsUrlFromApiBase("http://localhost:8000");
    assert.equal(url, "ws://localhost:8000/v1/realtime/ws");
    assert.equal(assertSafeCallingCardsWsUrl(url), true);
  });

  it("rejects websocket URLs that embed ticket or access_token", () => {
    assert.equal(
      assertSafeCallingCardsWsUrl("ws://localhost:8000/v1/realtime/ws?access_token=secret"),
      false,
    );
    assert.equal(
      assertSafeCallingCardsWsUrl("ws://localhost:8000/v1/realtime/ws?ticket=secret"),
      false,
    );
  });

  it("builds authenticate frame as first message shape", () => {
    const frame = buildCallingCardsAuthenticateFrame("t".repeat(32));
    assert.equal(frame.type, "authenticate");
    assert.equal(frame.ticket.length, 32);
  });

  it("client requests calling_cards purpose ticket and discards after send", () => {
    const client = read("src/realtime/client.ts");
    assert.match(client, /purpose:\s*"calling_cards"|purpose: "calling_cards"/);
    assert.match(client, /\/v1\/realtime\/tickets/);
    assert.match(client, /type: "authenticate"/);
    assert.match(client, /ticket = ""/);
    assert.match(client, /Never log the ticket/);
    assert.doesNotMatch(client, /access_token=\$\{/);
    assert.doesNotMatch(client, /\?ticket=/);
    assert.match(client, /scheduleReconnect|backoffMs/);
    assert.match(client, /getLiveAccessToken\(\)/);
  });

  it("ForegroundNotificationProvider still uses subscribeRealtime", () => {
    const provider = read("src/features/notifications/ForegroundNotificationProvider.tsx");
    assert.match(provider, /subscribeRealtime/);
    assert.match(provider, /calling_card\.created/);
    assert.match(provider, /message\.created/);
  });
});
