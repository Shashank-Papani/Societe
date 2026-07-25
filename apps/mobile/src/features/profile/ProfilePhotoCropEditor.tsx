import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Gesture, GestureDetector, GestureHandlerRootView } from "react-native-gesture-handler";
import Animated, { useAnimatedStyle, useSharedValue } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  applyPan,
  applyPinchWithFocal,
  clampScale,
  clampTranslation,
  computeMaxScale,
  computeMinScale,
} from "@/features/profile/profilePhotoCropMath";
import { exportCroppedProfilePhoto } from "@/features/profile/profilePhotoExport";

type Props = {
  visible: boolean;
  uri: string;
  imageWidth: number;
  imageHeight: number;
  onCancel: () => void;
  onUsePhoto: (cropped: {
    uri: string;
    mimeType: "image/jpeg";
    width: number;
    height: number;
  }) => void;
};

const WINDOW = Dimensions.get("window");

export function ProfilePhotoCropEditor(props: Props) {
  const [resetKey, setResetKey] = useState(0);

  return (
    <Modal visible={props.visible} animationType="fade" presentationStyle="fullScreen">
      {props.visible ? (
        <CropEditorBody
          key={`${props.uri}:${resetKey}`}
          uri={props.uri}
          imageWidth={props.imageWidth}
          imageHeight={props.imageHeight}
          onCancel={props.onCancel}
          onReset={() => setResetKey((n) => n + 1)}
          onUsePhoto={props.onUsePhoto}
        />
      ) : null}
    </Modal>
  );
}

function CropEditorBody({
  uri,
  imageWidth,
  imageHeight,
  onCancel,
  onReset,
  onUsePhoto,
}: Omit<Props, "visible"> & { onReset: () => void }) {
  const insets = useSafeAreaInsets();
  const cropSize = Math.min(WINDOW.width - 48, WINDOW.height * 0.48, 340);
  const minScale = useMemo(
    () => computeMinScale(imageWidth, imageHeight, cropSize),
    [imageWidth, imageHeight, cropSize],
  );
  const maxScale = useMemo(() => computeMaxScale(minScale), [minScale]);

  const scale = useSharedValue(minScale);
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);
  const startScale = useSharedValue(minScale);
  const startTX = useSharedValue(0);
  const startTY = useSharedValue(0);
  const pinchActive = useSharedValue(0);

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const pan = Gesture.Pan()
    .averageTouches(true)
    .onStart(() => {
      "worklet";
      startTX.value = translateX.value;
      startTY.value = translateY.value;
    })
    .onUpdate((event) => {
      "worklet";
      if (pinchActive.value === 1 || event.numberOfPointers > 1) {
        return;
      }
      const next = applyPan(
        {
          scale: scale.value,
          translateX: startTX.value,
          translateY: startTY.value,
        },
        event.translationX,
        event.translationY,
        { imageWidth, imageHeight, cropSize },
      );
      translateX.value = next.translateX;
      translateY.value = next.translateY;
    });

  const pinch = Gesture.Pinch()
    .onStart(() => {
      "worklet";
      pinchActive.value = 1;
      startScale.value = scale.value;
      startTX.value = translateX.value;
      startTY.value = translateY.value;
    })
    .onUpdate((event) => {
      "worklet";
      const focalX = event.focalX - WINDOW.width / 2;
      const focalY = event.focalY - WINDOW.height / 2;
      const next = applyPinchWithFocal({
        saved: {
          scale: startScale.value,
          translateX: startTX.value,
          translateY: startTY.value,
        },
        gestureScale: event.scale,
        focalX,
        focalY,
        minScale,
        maxScale,
        imageWidth,
        imageHeight,
        cropSize,
      });
      scale.value = next.scale;
      translateX.value = next.translateX;
      translateY.value = next.translateY;
    })
    .onEnd(() => {
      "worklet";
      pinchActive.value = 0;
      const clampedScale = clampScale(scale.value, minScale, maxScale);
      const clamped = clampTranslation(translateX.value, translateY.value, {
        imageWidth,
        imageHeight,
        cropSize,
        scale: clampedScale,
      });
      scale.value = clamped.scale;
      translateX.value = clamped.translateX;
      translateY.value = clamped.translateY;
    });

  const gesture = Gesture.Simultaneous(pan, pinch);

  const imageStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { scale: scale.value },
    ],
  }));

  const onUse = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const exported = await exportCroppedProfilePhoto({
        uri,
        imageWidth,
        imageHeight,
        cropSize,
        transform: {
          scale: scale.value,
          translateX: translateX.value,
          translateY: translateY.value,
        },
      });
      onUsePhoto({
        uri: exported.uri,
        mimeType: "image/jpeg",
        width: exported.width,
        height: exported.height,
      });
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Could not crop photo.");
    } finally {
      setExporting(false);
    }
  };

  const dim = "rgba(0,0,0,0.62)";
  const side = (WINDOW.width - cropSize) / 2;
  const topBand = (WINDOW.height - cropSize) / 2;

  return (
    <GestureHandlerRootView style={styles.root}>
      <View style={styles.root}>
        <GestureDetector gesture={gesture}>
          <View style={styles.stage} collapsable={false}>
            <Animated.Image
              source={{ uri }}
              style={[
                {
                  position: "absolute",
                  width: imageWidth,
                  height: imageHeight,
                  left: WINDOW.width / 2 - imageWidth / 2,
                  top: WINDOW.height / 2 - imageHeight / 2,
                },
                imageStyle,
              ]}
            />
          </View>
        </GestureDetector>

        <View style={StyleSheet.absoluteFill} pointerEvents="none">
          <View style={{ height: topBand, backgroundColor: dim }} />
          <View style={{ flexDirection: "row", height: cropSize }}>
            <View style={{ width: side, backgroundColor: dim }} />
            <View style={[styles.cropHole, { width: cropSize, height: cropSize }]} />
            <View style={{ width: side, backgroundColor: dim }} />
          </View>
          <View style={{ flex: 1, backgroundColor: dim }} />
        </View>

        <View
          pointerEvents="box-none"
          style={[
            styles.chrome,
            { paddingTop: insets.top + 8, paddingBottom: Math.max(insets.bottom, 12) + 8 },
          ]}
        >
          <View style={styles.topRow}>
            <Pressable onPress={onCancel} disabled={exporting} hitSlop={12}>
              <Text style={styles.chromeButton}>Cancel</Text>
            </Pressable>
            <Pressable onPress={onReset} disabled={exporting} hitSlop={12}>
              <Text style={styles.chromeButton}>Reset</Text>
            </Pressable>
            <Pressable onPress={() => void onUse()} disabled={exporting} hitSlop={12}>
              <Text style={[styles.chromeButton, styles.useButton]}>
                {exporting ? "Working…" : exportError ? "Retry" : "Use Photo"}
              </Text>
            </Pressable>
          </View>
          <View>
            <Text style={styles.helper}>Move and scale</Text>
            {exportError ? <Text style={styles.error}>{exportError}</Text> : null}
            {exporting ? <ActivityIndicator color="#f5f7fb" style={{ marginTop: 8 }} /> : null}
          </View>
        </View>
      </View>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#000" },
  stage: { ...StyleSheet.absoluteFill, backgroundColor: "#000" },
  cropHole: {
    borderRadius: 9999,
    borderWidth: 1.5,
    borderColor: "rgba(255,255,255,0.92)",
    backgroundColor: "transparent",
  },
  chrome: {
    ...StyleSheet.absoluteFill,
    justifyContent: "space-between",
    paddingHorizontal: 20,
  },
  topRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  chromeButton: { color: "#f5f7fb", fontSize: 17, fontWeight: "600" },
  useButton: { color: "#60a5fa" },
  helper: {
    color: "#e5e7eb",
    textAlign: "center",
    marginBottom: 8,
    fontSize: 15,
  },
  error: { color: "#fca5a5", textAlign: "center", marginBottom: 4 },
});
