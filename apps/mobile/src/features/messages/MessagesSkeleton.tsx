import { useEffect, useState } from "react";
import { AccessibilityInfo, Animated, StyleSheet, View } from "react-native";

import { colors } from "@/theme";

export function ConversationsSkeleton({ count = 6 }: { count?: number }) {
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
    <View style={styles.list} testID="conversations-skeleton">
      {Array.from({ length: count }, (_, index) => (
        <Animated.View key={index} style={[styles.row, { opacity }]}>
          <View style={styles.avatar} />
          <View style={styles.copy}>
            <View style={styles.lineWide} />
            <View style={styles.lineNarrow} />
          </View>
        </Animated.View>
      ))}
    </View>
  );
}

export function ThreadSkeleton({ count = 5 }: { count?: number }) {
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
        Animated.timing(opacity, { toValue: 0.85, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.4, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity, reduceMotion]);

  return (
    <View style={styles.thread} testID="thread-skeleton">
      {Array.from({ length: count }, (_, index) => (
        <Animated.View
          key={index}
          style={[
            styles.bubble,
            index % 2 === 0 ? styles.bubbleMine : styles.bubbleTheirs,
            { opacity },
          ]}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: 0 },
  row: {
    minHeight: 72,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.skeleton,
  },
  copy: { flex: 1, gap: 8 },
  lineWide: {
    width: "55%",
    height: 14,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
  },
  lineNarrow: {
    width: "80%",
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
  },
  thread: {
    flex: 1,
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 10,
    justifyContent: "flex-end",
  },
  bubble: {
    height: 44,
    borderRadius: 16,
    backgroundColor: colors.skeleton,
    maxWidth: "75%",
  },
  bubbleMine: { alignSelf: "flex-end", width: "58%" },
  bubbleTheirs: { alignSelf: "flex-start", width: "48%" },
});
