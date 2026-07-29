import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  formatPresenceDistance,
  formatPresenceMetaWithDistance,
  mapEligibilityReasonToButtonLabel,
  normalizeEligibilityReason,
} from "./presenceEligibility.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.join(here, "../../..");

function read(rel: string) {
  return readFileSync(path.join(mobileRoot, rel), "utf8");
}

describe("formatPresenceDistance", () => {
  it("formats zero and twenty meters as < 0.1 mi", () => {
    assert.equal(formatPresenceDistance(0), "< 0.1 mi");
    assert.equal(formatPresenceDistance(20), "< 0.1 mi");
  });

  it("formats ~160 m as 0.1 mi and ~322 m as 0.2 mi", () => {
    assert.equal(formatPresenceDistance(160), "0.1 mi");
    assert.equal(formatPresenceDistance(322), "0.2 mi");
  });

  it("formats one mile as 1.0 mi", () => {
    assert.equal(formatPresenceDistance(1609.344), "1.0 mi");
  });

  it("does not invent distance when missing", () => {
    assert.equal(formatPresenceDistance(null), null);
    assert.equal(formatPresenceDistance(undefined), null);
  });
});

describe("eligibility button copy mapping", () => {
  it("maps structured reasons to user-facing labels", () => {
    assert.equal(mapEligibilityReasonToButtonLabel("eligible"), "Verify Presence");
    assert.equal(mapEligibilityReasonToButtonLabel("outside"), "Not close enough");
    assert.equal(
      mapEligibilityReasonToButtonLabel("location_permission_denied"),
      "Enable location",
    );
    assert.equal(
      mapEligibilityReasonToButtonLabel("location_unavailable"),
      "Location unavailable",
    );
    assert.equal(mapEligibilityReasonToButtonLabel("location_stale"), "Refresh location");
    assert.equal(mapEligibilityReasonToButtonLabel("stale_evidence"), "Refresh location");
    assert.equal(
      mapEligibilityReasonToButtonLabel("accuracy_exceeds_venue_maximum"),
      "Improve location accuracy",
    );
    assert.equal(mapEligibilityReasonToButtonLabel("loading"), "Checking location…");
    assert.equal(mapEligibilityReasonToButtonLabel("network"), "Try again");
  });

  it("normalizes server outside reasons to outside", () => {
    assert.equal(normalizeEligibilityReason("outside"), "outside");
    assert.equal(normalizeEligibilityReason("outside_polygon_within_entry_buffer"), "outside");
  });
});

describe("Presence eligibility wiring contracts", () => {
  const liveMap = read("src/features/presence/PresenceLiveMap.tsx");
  const screen = read("src/features/presence/PresenceScreen.tsx");
  const eligibility = read("src/features/presence/presenceEligibility.ts");
  const hook = read("src/features/presence/usePresenceEligibility.ts");
  const api = read("src/features/presence/api.ts");
  const diagnostics = read("src/features/presence/PresenceEligibilityDiagnostics.tsx");

  it("card distance and button state share eligibility result", () => {
    assert.match(liveMap, /formatPresenceMetaWithDistance/);
    assert.match(liveMap, /mapEligibilityReasonToButtonLabel/);
    assert.match(liveMap, /eligibilityForSelected/);
    assert.match(screen, /usePresenceEligibility/);
    assert.match(api, /\/v1\/presence\/eligibility/);
    assert.doesNotMatch(liveMap, /distance_m: selected\.distance_m/);
    assert.doesNotMatch(eligibility, /0\.2 mi/);
  });

  it("loading shows Checking distance / Checking location", () => {
    assert.match(eligibility, /Checking distance…/);
    assert.match(eligibility, /Checking location…/);
    assert.equal(
      formatPresenceMetaWithDistance({
        category: "nightclub",
        distancePending: true,
        formatVenueType: () => "Nightclub",
      }),
      "Nightclub • Checking distance…",
    );
  });

  it("ignores stale responses when switching venues", () => {
    assert.match(hook, /requestTokenRef/);
    assert.match(hook, /token !== requestTokenRef\.current/);
    assert.match(hook, /result\.venue_id !== selectedId/);
  });

  it("hides development diagnostics outside __DEV__", () => {
    assert.match(diagnostics, /if\s*\(\s*!__DEV__\s*\)/);
    assert.match(diagnostics, /return null/);
    assert.match(diagnostics, /distance_meters/);
    assert.match(diagnostics, /allowed_radius_meters/);
  });

  it("keeps verification mutation server-authoritative", () => {
    const verify = read("src/features/presence/useVerifyPresence.ts");
    assert.match(verify, /submitPresenceEvidence|submitSimulatedPresence/);
    assert.match(screen, /useVerifyPresence/);
    assert.match(screen, /canVerify/);
    assert.doesNotMatch(screen, /eligible\s*=\s*true/);
  });
});
