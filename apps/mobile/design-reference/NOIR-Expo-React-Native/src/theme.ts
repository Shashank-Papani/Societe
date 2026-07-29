import { Platform } from "react-native";

export const colors = {
  black: "#010503",
  panel: "#06110c",
  panelAlt: "#09150f",
  border: "#14271d",
  lime: "#A8FF00",
  limeSoft: "#C9FF3D",
  gold: "#D4AF37",
  white: "#F7FAF8",
  muted: "#738179",
  mutedLight: "#9AA69F",
};

export const fonts = {
  sans: Platform.select({ ios: "Avenir Next", android: "sans-serif", default: "system-ui" }),
  sansHeavy: Platform.select({
    ios: "Avenir Next",
    android: "sans-serif-medium",
    default: "system-ui",
  }),
  serif: Platform.select({ ios: "Didot", android: "serif", default: "Georgia" }),
};
