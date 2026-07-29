import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import type { PresenceSnapshot } from "./api.ts";
import {
  haversineMeters,
  isActivelyPresentAtVenue,
  offsetLatLng,
  presenceStatusLabel,
  resolvePresentationState,
  shouldStartRetention,
  shouldTriggerMovementHeartbeat,
} from "./presenceRetention.ts";
import {
  FOREGROUND_HEARTBEAT_SECONDS,
  MOVEMENT_TRIGGER_METERS,
  RETENTION_RADIUS_METERS,
} from "./presenceRetentionPolicy.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.join(here, "../../..");

function read(rel: string) {
  return readFileSync(path.join(mobileRoot, rel), "utf8");
}

function snapshot(overrides: Partial<PresenceSnapshot> = {}): PresenceSnapshot {
  return {
    state: "verified",
    venue: { id: "venue-1", name: "Neon House" },
    verification_level: "standard",
    lease_expires_at: "2099-01-01T00:00:00Z",
    social_features_enabled: true,
    challenge: null,
    decision: "current",
    reasons: [],
    outside_confirmation_pending: false,
    ...overrides,
  };
}

describe("presence retention presentation", () => {
  it("maps verified to Presence Verified", () => {
    assert.equal(resolvePresentationState(snapshot()), "active");
    assert.equal(presenceStatusLabel("active"), "Presence Verified");
  });

  it("maps first outside / rechecking without removing verified UI immediately", () => {
    const state = resolvePresentationState(
      snapshot({ state: "rechecking", outside_confirmation_pending: true }),
    );
    assert.equal(state, "rechecking");
    assert.equal(presenceStatusLabel(state), "Rechecking your location…");
    assert.equal(isActivelyPresentAtVenue(snapshot({ state: "rechecking" }), "venue-1"), true);
  });

  it("maps grace to friendly copy", () => {
    assert.equal(resolvePresentationState(snapshot({ state: "degraded" })), "grace");
    assert.equal(presenceStatusLabel("grace"), "Keeping your presence active");
  });

  it("maps expired / revoked distinctly", () => {
    assert.equal(
      resolvePresentationState(
        snapshot({ state: "exited", decision: "expired", reasons: ["lease_expired"] }),
      ),
      "expired",
    );
    assert.equal(
      resolvePresentationState(
        snapshot({
          state: "exited",
          decision: "revoked",
          reasons: ["left_retention_radius"],
        }),
      ),
      "revoked",
    );
  });
});

describe("presence retention controller contracts", () => {
  it("starts only for active presence", () => {
    assert.equal(shouldStartRetention(snapshot()), true);
    assert.equal(shouldStartRetention(snapshot({ state: "rechecking" })), true);
    assert.equal(shouldStartRetention(snapshot({ state: "outside", venue: null })), false);
    assert.equal(shouldStartRetention(null), false);
  });

  it("uses 3-minute foreground interval and 30 m movement trigger", () => {
    assert.equal(FOREGROUND_HEARTBEAT_SECONDS, 180);
    assert.equal(MOVEMENT_TRIGGER_METERS, 30);
    assert.equal(
      shouldTriggerMovementHeartbeat({
        movedMeters: 30,
        secondsSinceLastSubmit: 45,
        accuracyMeters: 8,
      }),
      true,
    );
    assert.equal(
      shouldTriggerMovementHeartbeat({
        movedMeters: 5,
        secondsSinceLastSubmit: 45,
        accuracyMeters: 8,
      }),
      false,
    );
    assert.equal(
      shouldTriggerMovementHeartbeat({
        movedMeters: 40,
        secondsSinceLastSubmit: 10,
        accuracyMeters: 8,
      }),
      false,
    );
  });

  it("mounts global retention provider at authenticated root", () => {
    const layout = read("src/app/_layout.tsx");
    assert.match(layout, /PresenceRetentionProvider/);
    assert.match(layout, /backgroundPresenceTask/);
  });

  it("background task uses the same heartbeat endpoint helper", () => {
    const background = read("src/features/presence/backgroundPresenceTask.ts");
    const service = read("src/features/presence/PresenceHeartbeatService.ts");
    assert.match(background, /submitRetentionHeartbeat/);
    assert.match(service, /submitPresenceHeartbeat/);
    assert.match(background, /PRESENCE_GEOFENCE_TASK/);
    assert.match(background, /stopBackgroundRetention/);
  });

  it("does not revoke from geofence alone", () => {
    const background = read("src/features/presence/backgroundPresenceTask.ts");
    assert.match(background, /submitRetentionHeartbeat/);
    assert.doesNotMatch(background, /leavePresence/);
    assert.doesNotMatch(background, /state\s*=\s*["']revoked["']/);
  });

  it("keeps bottom navigation unchanged", () => {
    const tabBar = read("src/navigation/SocieteTabBar.tsx");
    assert.match(tabBar, /presence:\s*"presence"/);
    assert.match(tabBar, /testID=\{`tab-\$\{iconKey\}`\}/);
    assert.doesNotMatch(tabBar, /heartbeat|RetentionController/);
  });
});

describe("development fixtures", () => {
  it("builds deterministic distances from venue centroid", () => {
    const origin = { latitude: 34.0955, longitude: -118.344 };
    const inside = offsetLatLng(origin, -30, 0);
    const retention = offsetLatLng(origin, -200, 0);
    const outside = offsetLatLng(origin, -300, 0);
    assert.ok(haversineMeters(origin, inside) < 50);
    assert.ok(haversineMeters(origin, retention) > 160.9344);
    assert.ok(haversineMeters(origin, retention) < RETENTION_RADIUS_METERS);
    assert.ok(haversineMeters(origin, outside) > RETENTION_RADIUS_METERS);
  });

  it("fixture switch bumps location epoch (invalidates prior evidence)", () => {
    const provider = read("src/location/LocationProvider.ts");
    assert.match(provider, /locationEpoch/);
    assert.match(provider, /setDevLocationOverride/);
    assert.match(provider, /buildDevVenueFixture/);
  });
});
