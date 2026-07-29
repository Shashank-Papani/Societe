import { useEffect, useState } from "react";
import { AccessibilityInfo, Animated, StyleSheet, View } from "react-native";

import { discoverSurface } from "@/features/discover/discoverPresentation";
import { colors } from "@/theme";

export function DiscoverSkeletonList({ count = 3 }: { count?: number }) {
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
    <View style={styles.list} testID="discover-skeleton">
      {Array.from({ length: count }, (_, index) => (
        <Animated.View key={index} style={[styles.card, { opacity }]}>
          <View style={styles.footer}>
            <View style={styles.title} />
            <View style={styles.meta} />
            <View style={styles.crowd} />
          </View>
        </Animated.View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: discoverSurface.cardGap },
  card: {
    width: "100%",
    aspectRatio: discoverSurface.cardAspectRatio, // 16 / 9
    borderRadius: discoverSurface.cardRadius,
    backgroundColor: "#121212",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(255,255,255,0.04)",
    overflow: "hidden",
    padding: 16,
    justifyContent: "flex-end",
  },
  footer: { gap: 10 },
  title: {
    width: "68%",
    height: 26,
    borderRadius: 8,
    backgroundColor: colors.skeleton,
  },
  meta: {
    width: "54%",
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
  },
  crowd: {
    width: "36%",
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
  },
});
