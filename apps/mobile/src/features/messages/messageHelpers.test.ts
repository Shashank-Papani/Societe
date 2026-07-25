import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  mapQueueStateToMessageUi,
  shouldShowAsSent,
  validateMessageBody,
} from "./messageHelpers.ts";

describe("validateMessageBody", () => {
  it("rejects empty and whitespace", () => {
    assert.notEqual(validateMessageBody(""), null);
    assert.notEqual(validateMessageBody("   \n"), null);
  });

  it("accepts trimmed content within limit", () => {
    assert.equal(validateMessageBody(" hello "), null);
  });
});

describe("mapQueueStateToMessageUi", () => {
  it("never treats queued as sent", () => {
    assert.equal(shouldShowAsSent(mapQueueStateToMessageUi("queued")), false);
    assert.equal(shouldShowAsSent(mapQueueStateToMessageUi("sending")), false);
    assert.equal(shouldShowAsSent(mapQueueStateToMessageUi("server_confirmed")), true);
  });

  it("maps retryable and permanent failures", () => {
    assert.equal(mapQueueStateToMessageUi("failed_retryable"), "failed_retryable");
    assert.equal(mapQueueStateToMessageUi("failed_permanent"), "failed_permanent");
  });
});
