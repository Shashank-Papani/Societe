import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { deepLinkToHref, parseNotificationDeepLink } from "./deepLinks.ts";

const id = "11111111-1111-4111-8111-111111111111";

describe("Notification deep links", () => {
  it("accepts conversation links", () => {
    const parsed = parseNotificationDeepLink(`societe://conversation/${id}`);
    assert.deepEqual(parsed, { kind: "conversation", conversationId: id });
    assert.equal(deepLinkToHref(parsed!), `/messages/${id}`);
  });

  it("accepts calling card links", () => {
    const parsed = parseNotificationDeepLink(`societe://calling-card/${id}`);
    assert.deepEqual(parsed, { kind: "calling_card", callingCardId: id });
    assert.equal(deepLinkToHref(parsed!), "/(tabs)/connect");
  });

  it("accepts story and experience links safely", () => {
    assert.deepEqual(parseNotificationDeepLink(`societe://story/${id}`), {
      kind: "story",
      storyId: id,
    });
    assert.deepEqual(parseNotificationDeepLink("societe://experience"), {
      kind: "experience",
    });
    assert.equal(
      deepLinkToHref({ kind: "story", storyId: id }),
      "/(tabs)/experience",
    );
  });

  it("handles venue claim and organization invitation without management UI", () => {
    const claim = parseNotificationDeepLink(`societe://venue-claim/${id}`);
    assert.equal(claim?.kind, "venue_claim");
    assert.equal(deepLinkToHref(claim!), "/notifications/info?kind=venue_claim");
    const invite = parseNotificationDeepLink(`societe://organization-invitation/${id}`);
    assert.equal(invite?.kind, "organization_invitation");
    assert.equal(
      deepLinkToHref(invite!),
      "/notifications/info?kind=organization_invitation",
    );
  });

  it("rejects http/https and executable schemes", () => {
    assert.equal(parseNotificationDeepLink("https://evil.example/x"), null);
    assert.equal(parseNotificationDeepLink("http://evil.example/x"), null);
    assert.equal(parseNotificationDeepLink("javascript:alert(1)"), null);
    assert.equal(parseNotificationDeepLink("file:///etc/passwd"), null);
  });

  it("rejects unknown societe routes and malformed identifiers", () => {
    assert.equal(parseNotificationDeepLink("societe://unknown/thing"), null);
    assert.equal(parseNotificationDeepLink("societe://conversation/not-uuid"), null);
    assert.equal(parseNotificationDeepLink(`societe://conversation/${id}?x=1`), null);
    assert.equal(parseNotificationDeepLink(`societe://conversation/${id}/extra`), null);
  });
});
