import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  applyPan,
  applyPinchScale,
  applyPinchWithFocal,
  clampTranslation,
  computeMinScale,
  computeMaxScale,
  computePixelCropRect,
  resetTransform,
  resolveUploadUri,
  shouldUploadOnCancel,
} from "./profilePhotoCropMath.ts";

const CROP = 300;

describe("portrait image minimum scale", () => {
  it("covers the crop using the image width", () => {
    const min = computeMinScale(1080, 1920, CROP);
    assert.ok(Math.abs(min - CROP / 1080) < 1e-9);
    assert.ok(1080 * min >= CROP - 1e-6);
    assert.ok(1920 * min >= CROP - 1e-6);
  });
});

describe("landscape image minimum scale", () => {
  it("covers the crop using the image height", () => {
    const min = computeMinScale(1920, 1080, CROP);
    assert.ok(Math.abs(min - CROP / 1080) < 1e-9);
    assert.ok(1920 * min >= CROP - 1e-6);
    assert.ok(1080 * min >= CROP - 1e-6);
  });
});

describe("square image minimum scale", () => {
  it("covers the crop uniformly", () => {
    const min = computeMinScale(1000, 1000, CROP);
    assert.equal(min, CROP / 1000);
    assert.equal(computeMaxScale(min), min * 4);
  });
});

describe("pinch changes scale", () => {
  it("scales relative to the gesture start", () => {
    const min = computeMinScale(1000, 1000, CROP);
    const max = computeMaxScale(min);
    const next = applyPinchScale(min, 2, min, max);
    assert.equal(next, min * 2);
  });
});

describe("pan changes both translations", () => {
  it("updates x and y from the saved transform", () => {
    const min = computeMinScale(1000, 2000, CROP);
    const saved = { scale: min * 2, translateX: 0, translateY: 0 };
    const next = applyPan(saved, 40, -25, {
      imageWidth: 1000,
      imageHeight: 2000,
      cropSize: CROP,
    });
    assert.equal(next.translateX, 40);
    assert.equal(next.translateY, -25);
    assert.equal(next.scale, saved.scale);
  });
});

describe("translation clamping prevents blank crop areas", () => {
  it("clamps beyond the cover bounds", () => {
    const scale = computeMinScale(1000, 1000, CROP) * 2;
    const max = (1000 * scale - CROP) / 2;
    const clamped = clampTranslation(10_000, -10_000, {
      imageWidth: 1000,
      imageHeight: 1000,
      cropSize: CROP,
      scale,
    });
    assert.equal(clamped.translateX, max);
    assert.equal(clamped.translateY, -max);
  });
});

describe("zoom-out stops at minimum scale", () => {
  it("does not go below minScale", () => {
    const min = computeMinScale(800, 1200, CROP);
    const max = computeMaxScale(min);
    assert.equal(applyPinchScale(min, 0.1, min, max), min);
  });
});

describe("zoom-in stops at maximum scale", () => {
  it("does not exceed maxScale", () => {
    const min = computeMinScale(800, 1200, CROP);
    const max = computeMaxScale(min);
    assert.equal(applyPinchScale(min, 100, min, max), max);
  });
});

describe("Reset recenters the image", () => {
  it("restores minimum scale and zero translation", () => {
    const min = computeMinScale(900, 1600, CROP);
    const reset = resetTransform(min);
    assert.deepEqual(reset, { scale: min, translateX: 0, translateY: 0 });
  });
});

describe("crop coordinates change based on zoom and position", () => {
  it("produces a different rect after pan/zoom", () => {
    const imageWidth = 1000;
    const imageHeight = 1000;
    const min = computeMinScale(imageWidth, imageHeight, CROP);
    const centered = computePixelCropRect({
      imageWidth,
      imageHeight,
      cropSize: CROP,
      scale: min,
      translateX: 0,
      translateY: 0,
    });
    const zoomed = applyPinchWithFocal({
      saved: { scale: min, translateX: 0, translateY: 0 },
      gestureScale: 2,
      focalX: 0,
      focalY: 0,
      minScale: min,
      maxScale: computeMaxScale(min),
      imageWidth,
      imageHeight,
      cropSize: CROP,
    });
    const panned = applyPan(zoomed, 30, 0, { imageWidth, imageHeight, cropSize: CROP });
    const moved = computePixelCropRect({
      imageWidth,
      imageHeight,
      cropSize: CROP,
      ...panned,
    });
    assert.notDeepEqual(centered, moved);
    assert.ok(moved.width <= centered.width + 1);
    assert.ok(moved.originX >= 0);
    assert.ok(moved.originY >= 0);
    assert.ok(moved.originX + moved.width <= imageWidth);
    assert.ok(moved.originY + moved.height <= imageHeight);
  });
});

describe("Use Photo uploads the cropped URI rather than the original URI", () => {
  it("resolves only the cropped local file", () => {
    const originalUri = "file:///tmp/original.jpg";
    const croppedUri = "file:///tmp/cropped-1024.jpg";
    assert.equal(resolveUploadUri({ originalUri, croppedUri }), croppedUri);
    assert.notEqual(resolveUploadUri({ originalUri, croppedUri }), originalUri);
    assert.equal(resolveUploadUri({ originalUri, croppedUri: null }), null);
  });
});

describe("Cancel never uploads", () => {
  it("returns false for cancel upload gate", () => {
    assert.equal(shouldUploadOnCancel(), false);
  });
});
