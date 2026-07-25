/**
 * Pure Instagram-style crop math.
 * Functions used from Reanimated gesture worklets include a 'worklet' directive.
 */

export const PROFILE_PHOTO_EXPORT_SIZE = 1024;
export const PROFILE_PHOTO_MAX_ZOOM_MULTIPLIER = 4;

export type CropTransform = {
  scale: number;
  translateX: number;
  translateY: number;
};

export type PixelCropRect = {
  originX: number;
  originY: number;
  width: number;
  height: number;
};

export function computeMinScale(
  imageWidth: number,
  imageHeight: number,
  cropSize: number,
): number {
  "worklet";
  if (imageWidth <= 0 || imageHeight <= 0 || cropSize <= 0) {
    return 1;
  }
  return Math.max(cropSize / imageWidth, cropSize / imageHeight);
}

export function computeMaxScale(minScale: number): number {
  "worklet";
  return minScale * 4;
}

export function clampScale(scale: number, minScale: number, maxScale: number): number {
  "worklet";
  return Math.min(maxScale, Math.max(minScale, scale));
}

export function maxTranslation(
  imageSize: number,
  cropSize: number,
  scale: number,
): number {
  "worklet";
  return Math.max(0, (imageSize * scale - cropSize) / 2);
}

export function clampTranslation(
  translateX: number,
  translateY: number,
  params: {
    imageWidth: number;
    imageHeight: number;
    cropSize: number;
    scale: number;
  },
): CropTransform {
  "worklet";
  const maxX = maxTranslation(params.imageWidth, params.cropSize, params.scale);
  const maxY = maxTranslation(params.imageHeight, params.cropSize, params.scale);
  return {
    scale: params.scale,
    translateX: Math.min(maxX, Math.max(-maxX, translateX)),
    translateY: Math.min(maxY, Math.max(-maxY, translateY)),
  };
}

/** One-finger pan from a saved origin. */
export function applyPan(
  saved: CropTransform,
  translationX: number,
  translationY: number,
  params: {
    imageWidth: number;
    imageHeight: number;
    cropSize: number;
  },
): CropTransform {
  "worklet";
  return clampTranslation(saved.translateX + translationX, saved.translateY + translationY, {
    imageWidth: params.imageWidth,
    imageHeight: params.imageHeight,
    cropSize: params.cropSize,
    scale: saved.scale,
  });
}

/** Pinch scale relative to gesture start (no focal adjustment). */
export function applyPinchScale(
  savedScale: number,
  gestureScale: number,
  minScale: number,
  maxScale: number,
): number {
  "worklet";
  return clampScale(savedScale * gestureScale, minScale, maxScale);
}

/**
 * Pinch zoom centered on a focal point expressed relative to the crop/image
 * center (viewport coordinates).
 */
export function applyPinchWithFocal(params: {
  saved: CropTransform;
  gestureScale: number;
  focalX: number;
  focalY: number;
  minScale: number;
  maxScale: number;
  imageWidth: number;
  imageHeight: number;
  cropSize: number;
}): CropTransform {
  "worklet";
  const nextScale = applyPinchScale(
    params.saved.scale,
    params.gestureScale,
    params.minScale,
    params.maxScale,
  );
  const ratio = nextScale / params.saved.scale;
  const nextX = params.focalX - (params.focalX - params.saved.translateX) * ratio;
  const nextY = params.focalY - (params.focalY - params.saved.translateY) * ratio;
  return clampTranslation(nextX, nextY, {
    imageWidth: params.imageWidth,
    imageHeight: params.imageHeight,
    cropSize: params.cropSize,
    scale: nextScale,
  });
}

export function resetTransform(minScale: number): CropTransform {
  "worklet";
  return { scale: minScale, translateX: 0, translateY: 0 };
}

/**
 * Map the visible crop circle to an axis-aligned square in original image pixels.
 */
export function computePixelCropRect(params: {
  imageWidth: number;
  imageHeight: number;
  cropSize: number;
  scale: number;
  translateX: number;
  translateY: number;
}): PixelCropRect {
  const { imageWidth, imageHeight, cropSize, scale, translateX, translateY } = params;
  const sizeInImage = cropSize / scale;
  let originX = imageWidth / 2 + (-cropSize / 2 - translateX) / scale;
  let originY = imageHeight / 2 + (-cropSize / 2 - translateY) / scale;

  const maxOriginX = Math.max(0, imageWidth - sizeInImage);
  const maxOriginY = Math.max(0, imageHeight - sizeInImage);
  originX = Math.min(maxOriginX, Math.max(0, originX));
  originY = Math.min(maxOriginY, Math.max(0, originY));

  let width = Math.min(sizeInImage, imageWidth - originX);
  let height = Math.min(sizeInImage, imageHeight - originY);
  const side = Math.min(width, height);
  width = side;
  height = side;

  return {
    originX: Math.floor(originX),
    originY: Math.floor(originY),
    width: Math.max(1, Math.floor(width)),
    height: Math.max(1, Math.floor(height)),
  };
}

/** Upload must use the cropped local file, never the gallery original. */
export function resolveUploadUri(params: {
  originalUri: string;
  croppedUri: string | null | undefined;
}): string | null {
  if (params.croppedUri && params.croppedUri.length > 0) {
    return params.croppedUri;
  }
  return null;
}

export function shouldUploadOnCancel(): boolean {
  return false;
}
