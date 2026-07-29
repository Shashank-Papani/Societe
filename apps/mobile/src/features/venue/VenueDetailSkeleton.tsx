import { useEffect, useState } from "react";
import { AccessibilityInfo, Animated, StyleSheet, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors } from "@/theme";

export function VenueDetailSkeleton() {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const heroHeight = Math.min(340, Math.max(280, Math.round(width * 0.78)));
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
    <View style={styles.root} testID="venue-detail-skeleton">
      <Animated.View style={[styles.hero, { height: heroHeight, opacity }]} />
      <Animated.View style={[styles.body, { opacity }]}>
        <View style={styles.title} />
        <View style={styles.meta} />
        <View style={styles.line} />
        <View style={[styles.line, styles.lineShort]} />
        <View style={styles.card} />
        <View style={styles.card} />
      </Animated.View>
      <View style={[styles.sticky, { paddingBottom: Math.max(insets.bottom, 12) }]}>
        <View style={styles.stickyLeft} />
        <View style={styles.stickyBtn} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  hero: {
    width: "100%",
    backgroundColor: colors.surface,
  },
  body: {
    paddingHorizontal: 20,
    paddingTop: 20,
    gap: 12,
  },
  title: {
    width: "72%",
    height: 34,
    borderRadius: 8,
    backgroundColor: colors.skeleton,
  },
  meta: {
    width: "48%",
    height: 14,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
  },
  line: {
    width: "100%",
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
    marginTop: 4,
  },
  lineShort: { width: "78%" },
  card: {
    marginTop: 10,
    height: 96,
    borderRadius: 18,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  sticky: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingTop: 12,
    backgroundColor: colors.surface,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  stickyLeft: {
    flex: 1,
    height: 36,
    borderRadius: 8,
    backgroundColor: colors.skeleton,
  },
  stickyBtn: {
    width: 160,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.skeleton,
  },
});
