import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  PROFILE_PHOTO_MAX_BYTES,
  chooseOrReplaceLabel,
  mapCompleteResponseToPhase,
  profilePhotoStatusLabel,
  resolveVisibleProfilePhoto,
  shouldRefreshMeAfterPhase,
  validateProfilePhotoSelection,
} from "./profilePhotoUi.ts";

describe("placeholder state", () => {
  it("shows placeholder when there is no approved photo", () => {
    const display = resolveVisibleProfilePhoto({
      approvedUrl: null,
      phase: "idle",
    });
    assert.equal(display.mode, "placeholder");
    assert.equal(display.hasApprovedPhoto, false);
    assert.equal(display.uri, null);
    assert.equal(chooseOrReplaceLabel(display.hasApprovedPhoto), "Choose photo");
  });
});

describe("choose photo", () => {
  it("labels empty profiles as Choose photo", () => {
    assert.equal(chooseOrReplaceLabel(false), "Choose photo");
  });

  it("accepts a valid gallery selection payload", () => {
    const result = validateProfilePhotoSelection({
      uri: "file:///tmp/me.jpg",
      mimeType: "image/jpeg",
      byteSize: 120_000,
      width: 800,
      height: 800,
    });
    assert.equal(result.ok, true);
    if (result.ok) {
      assert.equal(result.asset.uri, "file:///tmp/me.jpg");
      assert.equal(result.asset.mimeType, "image/jpeg");
    }
  });

  it("rejects unsupported MIME and oversized files before upload", () => {
    assert.equal(
      validateProfilePhotoSelection({
        uri: "file:///tmp/x.gif",
        mimeType: "image/gif",
        byteSize: 1000,
      }).ok,
      false,
    );
    assert.equal(
      validateProfilePhotoSelection({
        uri: "file:///tmp/huge.jpg",
        mimeType: "image/jpeg",
        byteSize: PROFILE_PHOTO_MAX_BYTES + 1,
      }).ok,
      false,
    );
  });
});

describe("upload progress", () => {
  it("formats upload progress percentage", () => {
    assert.equal(profilePhotoStatusLabel("uploading", null), "Uploading…");
    assert.equal(profilePhotoStatusLabel("uploading", 0.42), "Uploading… 42%");
    assert.equal(profilePhotoStatusLabel("uploading", 1), "Uploading… 100%");
  });
});

describe("processing state", () => {
  it("keeps processing label and does not refresh me yet", () => {
    assert.equal(profilePhotoStatusLabel("processing", null), "Processing photo…");
    assert.equal(shouldRefreshMeAfterPhase("processing"), false);
    assert.equal(
      mapCompleteResponseToPhase({
        moderationStatus: "pending",
        published: false,
      }),
      "processing",
    );
  });
});

describe("approved replacement", () => {
  it("maps published approval and requests /v1/me refresh", () => {
    const phase = mapCompleteResponseToPhase({
      moderationStatus: "approved",
      published: true,
    });
    assert.equal(phase, "approved");
    assert.equal(shouldRefreshMeAfterPhase(phase), true);
    assert.equal(profilePhotoStatusLabel("approved", null), "Photo approved");
  });

  it("shows Replace photo once an approved URL exists", () => {
    const display = resolveVisibleProfilePhoto({
      approvedUrl: "https://cdn.example/profile.webp",
      phase: "approved",
    });
    assert.equal(display.mode, "remote");
    assert.equal(display.uri, "https://cdn.example/profile.webp");
    assert.equal(chooseOrReplaceLabel(display.hasApprovedPhoto), "Replace photo");
  });
});

describe("rejected upload", () => {
  it("maps rejected moderation and never treats it as displayable photo", () => {
    assert.equal(
      mapCompleteResponseToPhase({
        moderationStatus: "rejected",
        published: false,
      }),
      "rejected",
    );
    assert.equal(
      profilePhotoStatusLabel("rejected", null),
      "Photo rejected. Try another image.",
    );
    const display = resolveVisibleProfilePhoto({
      approvedUrl: null,
      phase: "rejected",
    });
    assert.equal(display.mode, "placeholder");
    assert.equal(display.hasApprovedPhoto, false);
  });
});

describe("existing approved photo remains during replacement processing", () => {
  it("keeps the prior approved remote URL while uploading and processing", () => {
    const prior = "https://cdn.example/old-approved.webp";
    for (const phase of ["uploading", "processing", "retry"] as const) {
      const display = resolveVisibleProfilePhoto({
        approvedUrl: prior,
        phase,
      });
      assert.equal(display.mode, "remote");
      assert.equal(display.uri, prior);
      assert.equal(display.hasApprovedPhoto, true);
      assert.equal(chooseOrReplaceLabel(true), "Replace photo");
    }
  });

  it("keeps approved marker (non-http) visible during processing", () => {
    const display = resolveVisibleProfilePhoto({
      approvedUrl: "profile-media:11111111-1111-4111-8111-111111111111",
      phase: "processing",
    });
    assert.equal(display.mode, "approved_marker");
    assert.equal(display.uri, null);
    assert.equal(display.hasApprovedPhoto, true);
  });
});
