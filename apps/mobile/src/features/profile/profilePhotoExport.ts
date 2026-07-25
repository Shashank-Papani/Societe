import {
  PROFILE_PHOTO_EXPORT_SIZE,
  computePixelCropRect,
  type CropTransform,
} from "@/features/profile/profilePhotoCropMath";

export async function exportCroppedProfilePhoto(params: {
  uri: string;
  imageWidth: number;
  imageHeight: number;
  cropSize: number;
  transform: CropTransform;
}): Promise<{ uri: string; width: number; height: number; mimeType: "image/jpeg" }> {
  // Lazy import so the crop editor can mount without requiring the native module
  // until the user taps Use Photo.
  const ImageManipulator = await import("expo-image-manipulator");

  const rect = computePixelCropRect({
    imageWidth: params.imageWidth,
    imageHeight: params.imageHeight,
    cropSize: params.cropSize,
    scale: params.transform.scale,
    translateX: params.transform.translateX,
    translateY: params.transform.translateY,
  });

  const result = await ImageManipulator.manipulateAsync(
    params.uri,
    [
      {
        crop: {
          originX: rect.originX,
          originY: rect.originY,
          width: rect.width,
          height: rect.height,
        },
      },
      {
        resize: {
          width: PROFILE_PHOTO_EXPORT_SIZE,
          height: PROFILE_PHOTO_EXPORT_SIZE,
        },
      },
    ],
    {
      compress: 0.9,
      format: ImageManipulator.SaveFormat.JPEG,
    },
  );

  return {
    uri: result.uri,
    width: result.width,
    height: result.height,
    mimeType: "image/jpeg",
  };
}
