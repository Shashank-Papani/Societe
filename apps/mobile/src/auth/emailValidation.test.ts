import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { isValidEmail } from "./emailValidation.ts";

describe("isValidEmail", () => {
  it("accepts a normal address", () => {
    assert.equal(isValidEmail("user@example.com"), true);
  });

  it("rejects empty and malformed values", () => {
    assert.equal(isValidEmail(""), false);
    assert.equal(isValidEmail("not-an-email"), false);
    assert.equal(isValidEmail("a@b"), false);
  });
});
