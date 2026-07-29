import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  avatarInitials,
  containsForbiddenConnectCopy,
  formatConnectionAvailable,
  friendlyConnectStateLabel,
  nearbyPersonAccessibilityLabel,
  presenceContextLabel,
} from "./connectPresentation.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(here, "../../..");

describe("Nearby people presentation", () => {
  it("renders labels from real display name and handle", () => {
    assert.equal(
      nearbyPersonAccessibilityLabel({
        user_id: "u1",
        display_name: "Alex Night",
        handle: "alex",
      }),
      "Alex Night, @alex",
    );
    assert.equal(avatarInitials("Alex Night", "alex"), "AN");
  });

  it("builds venue presence context without technical phrasing", () => {
    assert.equal(
      presenceContextLabel({
        venueName: "Echo Basement",
        verified: true,
        ghostOn: false,
      }),
      "Echo Basement · Presence verified",
    );
    assert.doesNotMatch(
      presenceContextLabel({
        venueName: "Echo Basement",
        verified: true,
        ghostOn: false,
      }) ?? "",
      /server-authoritative|Presence gate/i,
    );
  });
});

describe("Calling Card friendly states", () => {
  it("maps queue/card states to polished labels", () => {
    assert.equal(friendlyConnectStateLabel("queued"), "Waiting for connection");
    assert.equal(friendlyConnectStateLabel("sending"), "Sending…");
    assert.equal(friendlyConnectStateLabel("delivered"), "Sent");
    assert.equal(friendlyConnectStateLabel("accepted"), "Connected");
    assert.equal(friendlyConnectStateLabel("failed_retryable"), "Will retry automatically");
    assert.equal(friendlyConnectStateLabel("failed_permanent"), "Couldn’t send");
  });

  it("formats temporary connection availability", () => {
    const now = Date.parse("2026-07-25T12:00:00Z");
    assert.equal(
      formatConnectionAvailable("2026-07-25T12:28:00Z", now),
      "Connection available for 28 minutes",
    );
  });
});

describe("Connect screen production UI safety", () => {
  it("does not expose raw queue operation names outside diagnostics", () => {
    const screen = readFileSync(path.join(here, "ConnectScreen.tsx"), "utf8");
    const nearby = readFileSync(path.join(here, "NearbyPersonCard.tsx"), "utf8");
    const card = readFileSync(path.join(here, "CallingCardRow.tsx"), "utf8");
    for (const text of [nearby, card]) {
      assert.equal(containsForbiddenConnectCopy(text), false);
    }
    // Production UI must not render operationType; diagnostics stay collapsed under __DEV__.
    assert.doesNotMatch(screen, /\{op\.operationType\}/);
    assert.doesNotMatch(nearby, /Presence gate|server-authoritative/i);
    assert.match(screen, /DeveloperDiagnostics/);
    assert.match(screen, /Send Calling Card/);
    assert.match(screen, /CallingCardComposerSheet/);
    assert.match(screen, /enqueueCreateCallingCard/);
    assert.match(screen, /\/messages/);
    assert.doesNotMatch(screen, /Choose a reason, then send a Calling Card/);
    assert.equal(containsForbiddenConnectCopy("Send Calling Card"), false);
  });

  it("diagnostics render only under __DEV__", () => {
    const diagnostics = readFileSync(path.join(here, "DeveloperDiagnostics.tsx"), "utf8");
    assert.match(diagnostics, /if\s*\(\s*!__DEV__\s*\)/);
    assert.match(diagnostics, /Developer diagnostics/);
  });

  it("preserves all five bottom tabs", () => {
    const tabs = readFileSync(
      path.join(mobileRoot, "src/app/(tabs)/_layout.tsx"),
      "utf8",
    );
    assert.match(tabs, /name: "index"/);
    assert.match(tabs, /name: "presence"/);
    assert.match(tabs, /name: "experience"/);
    assert.match(tabs, /name: "connect"/);
    assert.match(tabs, /name: "profile"/);
  });

  it("uses ProfileAvatar fallback initials path", () => {
    const avatar = readFileSync(path.join(here, "ProfileAvatar.tsx"), "utf8");
    assert.match(avatar, /avatarInitials/);
    assert.match(avatar, /onError/);
  });
});
