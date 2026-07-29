import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { reasonCodeLabel } from "./queueHelpers.ts";

const here = path.dirname(fileURLToPath(import.meta.url));

describe("Calling Card composer UX", () => {
  it("keeps reason chips off the main Connect header", () => {
    const screen = readFileSync(path.join(here, "ConnectScreen.tsx"), "utf8");
    assert.doesNotMatch(screen, /Choose a reason, then send a Calling Card/);
    assert.doesNotMatch(screen, /CALLING_CARD_REASON_CODES\.map/);
    assert.match(screen, /CallingCardComposerSheet/);
  });

  it("opens composer from nearby person interactions", () => {
    const screen = readFileSync(path.join(here, "ConnectScreen.tsx"), "utf8");
    const nearby = readFileSync(path.join(here, "NearbyPersonCard.tsx"), "utf8");
    assert.match(screen, /openComposer/);
    assert.match(nearby, /onSelect/);
    assert.match(nearby, /testID=\{`nearby-person-\$\{person\.user_id\}`\}/);
  });

  it("hosts preset reasons and custom message inside the composer", () => {
    const composer = readFileSync(path.join(here, "CallingCardComposerSheet.tsx"), "utf8");
    assert.match(composer, /testID="calling-card-composer"/);
    assert.match(composer, /testID="calling-card-composer-reasons"/);
    assert.match(composer, /CALLING_CARD_REASON_CODES\.map/);
    assert.match(composer, /Add a message…/);
    assert.match(composer, /testID="calling-card-custom-message"/);
    assert.match(composer, /maxLength=\{CUSTOM_MESSAGE_MAX\}/);
    assert.match(composer, /export const CUSTOM_MESSAGE_MAX = 160/);
  });

  it("disables send without preset or message and guards double submit", () => {
    const composer = readFileSync(path.join(here, "CallingCardComposerSheet.tsx"), "utf8");
    assert.match(composer, /const canSend = Boolean\(reasonCode \|\| trimmed\) && !submitting/);
    assert.match(composer, /disabled=\{!canSend\}/);
    assert.match(composer, /testID="calling-card-composer-send"/);
    assert.match(composer, /testID="calling-card-composer-cancel"/);
  });

  it("uses product reason labels", () => {
    assert.equal(reasonCodeLabel("great_conversation"), "Great conversation");
    assert.equal(reasonCodeLabel("LOVE_THE_DANCE_MOVES"), "Love the dance moves");
  });

  it("shows pending and message states on nearby cards", () => {
    const screen = readFileSync(path.join(here, "ConnectScreen.tsx"), "utf8");
    assert.match(screen, /"Pending"/);
    assert.match(screen, /"Message"/);
    assert.match(screen, /"Send Calling Card"/);
    assert.match(screen, /actionPending=\{relation === "pending" \|\| relation === "sending"\}/);
  });

  it("renders preset and custom message on incoming cards", () => {
    const row = readFileSync(path.join(here, "CallingCardRow.tsx"), "utf8");
    assert.match(row, /custom_message/);
    assert.match(row, /calling-card-reason-/);
    assert.match(row, /calling-card-message-/);
  });

  it("preserves draft message after failed send", () => {
    const composer = readFileSync(path.join(here, "CallingCardComposerSheet.tsx"), "utf8");
    const screen = readFileSync(path.join(here, "ConnectScreen.tsx"), "utf8");
    assert.match(composer, /failed send \(same key\) preserves the entered message/);
    assert.match(composer, /submitError/);
    assert.match(screen, /key=\{composerPerson\?\.user_id \?\? "composer-closed"\}/);
  });

  it("cancel closes without queueing", () => {
    const screen = readFileSync(path.join(here, "ConnectScreen.tsx"), "utf8");
    assert.match(screen, /onClose=\{\(\) => \{/);
    assert.doesNotMatch(
      screen,
      /onClose=\{\(\) => \{\s*void enqueueCreateCallingCard/,
    );
  });
});
