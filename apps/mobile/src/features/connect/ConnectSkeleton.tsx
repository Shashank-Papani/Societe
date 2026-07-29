import { useEffect, useState } from "react";
import { AccessibilityInfo, Animated, StyleSheet, View } from "react-native";

import { colors } from "@/theme";

export function ConnectSkeleton({ count = 3 }: { count?: number }) {
  const [reduceMotion, setReduceMotion] = useState(false);
  const opacity = useState(() => new Animated.Value(0.55))[0];

  useEffect(() => {
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (mounted) {
        setReduceMotion(Boolean(enabled));
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (reduceMotion) {
      opacity.setValue(0.55);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.9, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.4, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity, reduceMotion]);

  return (
    <View style={styles.list} testID="connect-skeleton">
      {Array.from({ length: count }, (_, index) => (
        <Animated.View key={index} style={[styles.card, { opacity }]}>
          <View style={styles.row}>
            <View style={styles.avatar} />
            <View style={styles.copy}>
              <View style={styles.lineWide} />
              <View style={styles.lineNarrow} />
            </View>
          </View>
          <View style={styles.button} />
        </Animated.View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: 12 },
  card: {
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 16,
    gap: 14,
  },
  row: { flexDirection: "row", gap: 12, alignItems: "center" },
  avatar: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.skeleton,
  },
  copy: { flex: 1, gap: 8 },
  lineWide: {
    width: "70%",
    height: 16,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
  },
  lineNarrow: {
    width: "40%",
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
  },
  button: {
    height: 44,
    borderRadius: 999,
    backgroundColor: colors.skeleton,
  },
});
