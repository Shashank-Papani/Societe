import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { mapOutsidePresenceReasons, mapPresenceError } from "./presenceErrors.ts";

describe("Presence error mapping", () => {
  it("shows friendly too-far copy", () => {
    const mapped = mapPresenceError({
      status: 400,
      code: "OUTSIDE_GEOFENCE",
      message: "Point outside polygon",
    });
    assert.equal(mapped.title, "Too far away");
    assert.match(mapped.body, /closer to this venue/i);
  });

  it("shows friendly permission and network copy", () => {
    assert.match(
      mapPresenceError(new Error("Location permission denied or unavailable.")).body,
      /Location access is required/i,
    );
    assert.match(
      mapPresenceError({ status: 0, code: "NETWORK", message: "Failed to fetch" }).body,
      /Check your connection/i,
    );
  });

  it("maps outside snapshot reasons", () => {
    const mapped = mapOutsidePresenceReasons(["outside_polygon"]);
    assert.equal(mapped.code, "OUTSIDE");
  });
});
