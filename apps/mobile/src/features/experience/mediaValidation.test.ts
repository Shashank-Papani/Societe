import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MAX_IMAGE_BYTES,
  mapLifecycleToPhase,
  resolveImageMimeType,
  validateSelectedImage,
} from "./mediaValidation.ts";

describe("resolveImageMimeType", () => {
  it("prefers an allowed declared MIME", () => {
    assert.equal(
      resolveImageMimeType({
        mimeType: "image/png",
        fileName: "x.jpg",
        uri: "file:///tmp/x.jpg",
      }),
      "image/png",
    );
  });

  it("infers JPEG from the file name when MIME is missing", () => {
    assert.equal(
      resolveImageMimeType({
        mimeType: null,
        fileName: "night.jpg",
        uri: "file:///tmp/night",
      }),
      "image/jpeg",
    );
  });

  it("rejects video MIME types", () => {
    assert.equal(
      resolveImageMimeType({
        mimeType: "video/mp4",
        uri: "file:///tmp/clip.mp4",
      }),
      null,
    );
  });
});

describe("validateSelectedImage", () => {
  it("accepts a normal JPEG selection", () => {
    const result = validateSelectedImage({
      uri: "file:///tmp/photo.jpg",
      mimeType: "image/jpeg",
      byteSize: 240_000,
      width: 1080,
      height: 1920,
    });
    assert.equal(result.ok, true);
    if (result.ok) {
      assert.equal(result.asset.mediaType, "image");
      assert.equal(result.asset.byteSize, 240_000);
    }
  });

  it("rejects oversized files", () => {
    const result = validateSelectedImage({
      uri: "file:///tmp/huge.jpg",
      mimeType: "image/jpeg",
      byteSize: MAX_IMAGE_BYTES + 1,
    });
    assert.equal(result.ok, false);
  });

  it("rejects oversize dimensions when known", () => {
    const result = validateSelectedImage({
      uri: "file:///tmp/wide.jpg",
      mimeType: "image/jpeg",
      byteSize: 1000,
      width: 9000,
      height: 100,
    });
    assert.equal(result.ok, false);
  });

  it("rejects a missing URI", () => {
    const result = validateSelectedImage({
      uri: "",
      mimeType: "image/jpeg",
      byteSize: 1000,
    });
    assert.equal(result.ok, false);
  });
});

describe("mapLifecycleToPhase", () => {
  it("maps ready/published to published", () => {
    assert.equal(mapLifecycleToPhase("ready", "published"), "published");
  });

  it("maps processing states to processing", () => {
    assert.equal(mapLifecycleToPhase("moderation_pending", null), "processing");
  });

  it("maps invalid to rejected", () => {
    assert.equal(mapLifecycleToPhase("invalid", "rejected"), "rejected");
  });
});
