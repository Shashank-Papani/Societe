import { StyleSheet, type TextStyle } from "react-native";

import { colors } from "@/theme/colors";
import { fontFamilies } from "@/theme/fonts";

export const typography = StyleSheet.create({
  display: {
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 42,
    color: colors.textPrimary,
  },
  screenTitle: {
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 36,
    color: colors.textPrimary,
  },
  heroTitle: {
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 32,
    color: colors.textPrimary,
  },
  sectionTitle: {
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 24,
    color: colors.textPrimary,
  },
  cardTitle: {
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 26,
    color: colors.textPrimary,
  },
  body: {
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
    color: colors.textPrimary,
  },
  bodySmall: {
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    color: colors.textSecondary,
  },
  caption: {
    fontFamily: fontFamilies.geistMedium,
    fontSize: 11,
    color: colors.textSecondary,
  },
  button: {
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 15,
    color: colors.neonText,
  },
  badge: {
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 11,
    letterSpacing: 0.6,
    color: colors.neon,
  },
});

export type TypographyStyle = TextStyle;
