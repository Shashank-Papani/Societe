import type { ReactNode } from "react";
import { ScrollView, StyleSheet, View, type ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, screenPadding, spacing } from "@/theme";

type Props = {
  children: ReactNode;
  scroll?: boolean;
  testID?: string;
  contentStyle?: ViewStyle;
  edges?: ("top" | "right" | "bottom" | "left")[];
};

export function NoirScreen({
  children,
  scroll = true,
  testID,
  contentStyle,
  edges = ["top", "left", "right"],
}: Props) {
  if (!scroll) {
    return (
      <SafeAreaView style={styles.safe} edges={edges} testID={testID}>
        <View style={[styles.content, contentStyle]}>{children}</View>
      </SafeAreaView>
    );
  }
  return (
    <SafeAreaView style={styles.safe} edges={edges} testID={testID}>
      <ScrollView
        contentContainerStyle={[styles.content, contentStyle]}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.backgroundPrimary },
  content: {
    paddingHorizontal: screenPadding.default,
    paddingTop: spacing.xs,
    paddingBottom: spacing.xxxl,
    gap: spacing.xl,
  },
});
