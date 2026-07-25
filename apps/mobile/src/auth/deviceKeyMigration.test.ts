import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  decideLegacyRawMigration,
  scopedDeviceIdKey,
  scopedInstallationIdKey,
  subjectSecureStoreSuffix,
} from "./deviceKeys.ts";

/**
 * Simulates the post-OTP SecureStore writes using an in-memory map.
 * Ensures email subjects only touch hashed keys.
 */
function simulateOtpDeviceBinding(store: Map<string, string>, subject: string) {
  const installationId = "11111111-1111-4111-8111-111111111111";
  const deviceId = "22222222-2222-4222-8222-222222222222";
  store.set(scopedInstallationIdKey(subject), installationId);
  store.set(scopedDeviceIdKey(subject), deviceId);
  return { installationId, deviceId };
}

describe("OTP device binding namespaces", () => {
  it("registers OTP device under hashed subject keys only", () => {
    const store = new Map<string, string>();
    const subject = "email:user@example.com";
    const { installationId, deviceId } = simulateOtpDeviceBinding(store, subject);

    assert.equal(store.get(scopedInstallationIdKey(subject)), installationId);
    assert.equal(store.get(scopedDeviceIdKey(subject)), deviceId);
    for (const key of store.keys()) {
      assert.equal(key.includes("@"), false);
      assert.equal(key.includes(":"), false);
      assert.match(key, /^societe\.(installation_id|device_id)\.[a-f0-9]{64}$/);
    }
  });

  it("switching OTP user and Dev Alpha uses distinct device ids", () => {
    const store = new Map<string, string>();
    const otpSubject = "email:alice@example.com";
    const alpha = "dev-user-alpha";
    store.set(scopedDeviceIdKey(otpSubject), "otp-device");
    store.set(scopedDeviceIdKey(alpha), "alpha-device");
    assert.notEqual(store.get(scopedDeviceIdKey(otpSubject)), store.get(scopedDeviceIdKey(alpha)));
    assert.notEqual(subjectSecureStoreSuffix(otpSubject), subjectSecureStoreSuffix(alpha));
  });

  it("session restoration reads hashed key before legacy for Alpha", () => {
    assert.equal(
      decideLegacyRawMigration("dev-user-alpha", "new-hashed-device", "old-raw-device"),
      "use-hashed",
    );
    assert.equal(
      decideLegacyRawMigration("dev-user-alpha", null, "old-raw-device"),
      "migrate-legacy-raw",
    );
  });
});
