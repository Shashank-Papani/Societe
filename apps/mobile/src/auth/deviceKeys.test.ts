import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { scopedDeviceIdKey, scopedInstallationIdKey } from "./deviceKeys.ts";

describe("persona device key namespacing", () => {
  it("generates separate persistent keys for Alpha and Beta", () => {
    assert.equal(scopedDeviceIdKey("dev-user-alpha"), "societe.device_id.dev-user-alpha");
    assert.equal(scopedDeviceIdKey("dev-user-beta"), "societe.device_id.dev-user-beta");
    assert.equal(
      scopedInstallationIdKey("dev-user-alpha"),
      "societe.installation_id.dev-user-alpha",
    );
    assert.equal(
      scopedInstallationIdKey("dev-user-beta"),
      "societe.installation_id.dev-user-beta",
    );
    assert.notEqual(
      scopedDeviceIdKey("dev-user-alpha"),
      scopedDeviceIdKey("dev-user-beta"),
    );
    assert.notEqual(
      scopedInstallationIdKey("dev-user-alpha"),
      scopedInstallationIdKey("dev-user-beta"),
    );
  });

  it("never reuses Beta device key for Alpha", () => {
    const alpha = scopedDeviceIdKey("dev-user-alpha");
    const beta = scopedDeviceIdKey("dev-user-beta");
    assert.equal(alpha.includes("beta"), false);
    assert.equal(beta.includes("alpha"), false);
  });
});
