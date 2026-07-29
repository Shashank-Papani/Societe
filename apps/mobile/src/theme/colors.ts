/** Société noir design tokens — keep screens free of ad-hoc hex values. */
export const colors = {
  // Canonical vision tokens
  backgroundPrimary: "#040907",
  backgroundSecondary: "#07100B",
  surfaceSolid: "#0A150F",
  surfaceElevated: "#0D1A13",
  surfaceTranslucent: "rgba(10, 21, 15, 0.78)",
  surfaceGlass: "rgba(20, 26, 22, 0.84)",
  surfacePressed: "rgba(185, 249, 8, 0.08)",
  borderSubtle: "rgba(255, 255, 255, 0.07)",
  borderMedium: "rgba(255, 255, 255, 0.12)",
  borderActive: "rgba(185, 249, 8, 0.42)",
  textPrimary: "#FFFFFF",
  textSecondary: "#8FA39D",
  textTertiary: "#687873",
  neon: "#B9F908",
  neonPressed: "#9ED906",
  neonText: "#040907",
  gold: "#E2B857",
  danger: "#FF6B6B",
  warning: "#F4B94A",
  success: "#B9F908",
  overlayDark: "rgba(0, 0, 0, 0.66)",
  overlayHeavy: "rgba(0, 0, 0, 0.82)",

  // Backward-compatible aliases used across existing screens
  background: "#040907",
  surface: "#0A150F",
  border: "rgba(255, 255, 255, 0.07)",
  lime: "#B9F908",
  limeInk: "#040907",
  overlayTop: "rgba(4, 9, 7, 0.15)",
  overlayBottom: "rgba(4, 9, 7, 0.92)",
  skeleton: "rgba(143, 163, 157, 0.18)",
} as const;

export type ColorToken = keyof typeof colors;
