import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import {
  Dimensions,
  ImageBackground,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  WELCOME_DESCRIPTION,
  WELCOME_INK,
  WELCOME_LIME,
  WELCOME_MUTED,
  WELCOME_PRIMARY_LABEL,
  WELCOME_SECONDARY_LABEL,
  WELCOME_SUBTITLE,
  WELCOME_WORDMARK,
  resolveWelcomeAuthRoute,
} from "@/features/auth/welcomeContent";
import { fontFamilies } from "@/theme/fonts";

const BACKGROUND = require("../../../assets/images/welcome-page-background.png");

export function WelcomeScreen() {
  const router = useRouter();
  const width = Dimensions.get("window").width;
  const height = Dimensions.get("window").height;
  const wordmarkSize = width < 360 ? 64 : width < 400 ? 74 : 84;
  const verticalGap = height < 700 ? 12 : 18;

  function enterAuth() {
    router.push(resolveWelcomeAuthRoute());
  }

  return (
    <ImageBackground
      source={BACKGROUND}
      resizeMode="cover"
      style={styles.background}
      accessibilityIgnoresInvertColors
    >
      <LinearGradient
        colors={["rgba(4, 9, 7, 0.35)", "rgba(4, 9, 7, 0.55)", "rgba(4, 9, 7, 0.88)"]}
        locations={[0, 0.45, 1]}
        style={StyleSheet.absoluteFill}
      />
      <SafeAreaView style={styles.safe} edges={["top", "bottom", "left", "right"]}>
        <View style={styles.column}>
          <View style={styles.topSpacer} />

          <View style={[styles.brandBlock, { gap: verticalGap }]}>
            <Text
              style={[styles.wordmark, { fontSize: wordmarkSize, lineHeight: wordmarkSize * 1.05 }]}
              accessibilityRole="header"
            >
              {WELCOME_WORDMARK}
            </Text>
            <View style={styles.accentLine} />
            <Text style={styles.subtitle}>{WELCOME_SUBTITLE}</Text>
            <Text style={styles.description}>{WELCOME_DESCRIPTION}</Text>
          </View>

          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Enter Société"
              onPress={enterAuth}
              style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}
            >
              <Text style={styles.primaryLabel}>{WELCOME_PRIMARY_LABEL}</Text>
            </Pressable>

            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Members log in"
              onPress={enterAuth}
              style={({ pressed }) => [styles.secondaryButton, pressed && styles.pressed]}
            >
              <Text style={styles.secondaryLabel}>{WELCOME_SECONDARY_LABEL}</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    </ImageBackground>
  );
}

const styles = StyleSheet.create({
  background: {
    flex: 1,
    backgroundColor: WELCOME_INK,
  },
  safe: {
    flex: 1,
  },
  column: {
    flex: 1,
    justifyContent: "space-between",
    paddingHorizontal: 32,
  },
  topSpacer: {
    minHeight: 12,
  },
  brandBlock: {
    alignItems: "center",
    paddingVertical: 8,
  },
  wordmark: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.instrumentSerif,
    textAlign: "center",
    letterSpacing: -1.5,
  },
  accentLine: {
    width: 40,
    height: 2,
    backgroundColor: WELCOME_LIME,
  },
  subtitle: {
    color: WELCOME_LIME,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 13.5,
    letterSpacing: 2.2,
    textAlign: "center",
    textTransform: "uppercase",
  },
  description: {
    maxWidth: 336,
    color: "rgba(255,255,255,0.8)",
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 16,
    lineHeight: 26,
    textAlign: "center",
  },
  actions: {
    gap: 14,
    paddingBottom: 8,
  },
  primaryButton: {
    height: 56,
    minHeight: 56,
    borderRadius: 28,
    backgroundColor: WELCOME_LIME,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: WELCOME_LIME,
    shadowOpacity: 0.45,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 0 },
    elevation: 6,
  },
  primaryLabel: {
    color: WELCOME_INK,
    fontFamily: fontFamilies.geistBold,
    fontSize: 15.5,
    letterSpacing: 0.4,
  },
  secondaryButton: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 10,
  },
  secondaryLabel: {
    color: WELCOME_MUTED,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
    letterSpacing: 0.6,
  },
  pressed: {
    opacity: 0.88,
  },
});
