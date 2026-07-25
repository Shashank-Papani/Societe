import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, it } from "node:test";

import { subjectFromAccessToken } from "./authSubject.ts";
import {
  decideLegacyRawMigration,
  isSecureStoreSafeKeySegment,
  legacyRawScopedDeviceIdKey,
  scopedDeviceIdKey,
  scopedInstallationIdKey,
  sha256HexUtf8,
  subjectSecureStoreSuffix,
} from "./deviceKeys.ts";

describe("subjectSecureStoreSuffix", () => {
  it("hashes email subjects containing ':' and '@'", () => {
    const subject = "email:user@example.com";
    const suffix = subjectSecureStoreSuffix(subject);
    assert.equal(suffix, createHash("sha256").update(subject, "utf8").digest("hex"));
    assert.equal(isSecureStoreSafeKeySegment(suffix), true);
    assert.match(suffix, /^[a-f0-9]{64}$/);
    assert.equal(scopedDeviceIdKey(subject), `societe.device_id.${suffix}`);
    assert.equal(scopedInstallationIdKey(subject), `societe.installation_id.${suffix}`);
    // Raw email characters must never appear in the SecureStore key.
    assert.equal(scopedDeviceIdKey(subject).includes("@"), false);
    assert.equal(scopedDeviceIdKey(subject).includes(":"), false);
  });

  it("is deterministic and collision-resistant for similar subjects", () => {
    const a = "email:user@example.com";
    const b = "email:user@example.comx";
    assert.equal(subjectSecureStoreSuffix(a), subjectSecureStoreSuffix(a));
    assert.notEqual(subjectSecureStoreSuffix(a), subjectSecureStoreSuffix(b));
    assert.notEqual(scopedDeviceIdKey(a), scopedDeviceIdKey(b));
    assert.notEqual(scopedInstallationIdKey(a), scopedInstallationIdKey(b));
  });

  it("matches Node crypto for Dev Alpha/Beta subjects", () => {
    for (const subject of ["dev-user-alpha", "dev-user-beta", "local-dev-user"]) {
      assert.equal(
        sha256HexUtf8(subject),
        createHash("sha256").update(subject, "utf8").digest("hex"),
      );
      assert.equal(isSecureStoreSafeKeySegment(subject), true);
      assert.equal(
        scopedDeviceIdKey(subject),
        `societe.device_id.${createHash("sha256").update(subject, "utf8").digest("hex")}`,
      );
    }
  });

  it("keeps Alpha and Beta device namespaces distinct", () => {
    const alpha = scopedDeviceIdKey("dev-user-alpha");
    const beta = scopedDeviceIdKey("dev-user-beta");
    assert.notEqual(alpha, beta);
    assert.equal(alpha.startsWith("societe.device_id."), true);
    assert.equal(beta.startsWith("societe.device_id."), true);
  });
});

describe("legacy raw migration decision", () => {
  it("prefers the hashed key when present", () => {
    assert.equal(
      decideLegacyRawMigration("dev-user-alpha", "hashed-value", "legacy-value"),
      "use-hashed",
    );
  });

  it("migrates Dev Alpha/Beta legacy raw keys when hashed is empty", () => {
    assert.equal(
      decideLegacyRawMigration("dev-user-alpha", null, "uuid-alpha"),
      "migrate-legacy-raw",
    );
    assert.equal(
      decideLegacyRawMigration("dev-user-beta", null, "uuid-beta"),
      "migrate-legacy-raw",
    );
    assert.equal(
      legacyRawScopedDeviceIdKey("dev-user-alpha"),
      "societe.device_id.dev-user-alpha",
    );
  });

  it("does not migrate unsafe email subjects via raw keys", () => {
    assert.equal(
      decideLegacyRawMigration("email:user@example.com", null, "should-not-use"),
      "miss",
    );
    assert.equal(isSecureStoreSafeKeySegment("email:user@example.com"), false);
  });

  it("does not migrate another subject's value when hashed already set", () => {
    assert.equal(
      decideLegacyRawMigration("dev-user-beta", "beta-device", "alpha-device"),
      "use-hashed",
    );
  });
});

describe("subjectFromAccessToken", () => {
  it("reads sub for session restoration / OTP", () => {
    const payload = Buffer.from(
      JSON.stringify({ sub: "email:user@example.com", handle: "alice" }),
      "utf8",
    ).toString("base64url");
    const token = `hdr.${payload}.sig`;
    assert.equal(subjectFromAccessToken(token), "email:user@example.com");
  });

  it("reads Dev Alpha subject from access token", () => {
    const payload = Buffer.from(JSON.stringify({ sub: "dev-user-alpha" }), "utf8").toString(
      "base64url",
    );
    assert.equal(subjectFromAccessToken(`x.${payload}.y`), "dev-user-alpha");
  });
});

describe("OTP vs persona device namespaces", () => {
  it("OTP email subject and Dev Alpha never share SecureStore keys", () => {
    const otp = "email:alice@example.com";
    const alpha = "dev-user-alpha";
    assert.notEqual(scopedDeviceIdKey(otp), scopedDeviceIdKey(alpha));
    assert.notEqual(scopedInstallationIdKey(otp), scopedInstallationIdKey(alpha));
  });
});
