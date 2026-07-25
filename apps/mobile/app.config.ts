import type { ConfigContext, ExpoConfig } from "expo/config";

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: "Société",
  slug: "societe",
  version: "0.1.0",
  orientation: "portrait",
  icon: "./assets/images/icon.png",
  scheme: "societe",
  userInterfaceStyle: "automatic",
  ios: {
    icon: "./assets/expo.icon",
    bundleIdentifier: "com.societe.app",
  },
  android: {
    package: "com.societe.app",
    adaptiveIcon: {
      backgroundColor: "#E6F4FE",
      foregroundImage: "./assets/images/android-icon-foreground.png",
      backgroundImage: "./assets/images/android-icon-background.png",
      monochromeImage: "./assets/images/android-icon-monochrome.png",
    },
    predictiveBackGestureEnabled: false,
  },
  web: {
    output: "static",
    favicon: "./assets/images/favicon.png",
  },
  plugins: [
    "expo-router",
    "expo-secure-store",
    "expo-sqlite",
    "expo-dev-client",
    [
      "expo-location",
      {
        locationWhenInUsePermission:
          "Société uses your location to verify you are at a venue.",
      },
    ],
    [
      "expo-image-picker",
      {
        photosPermission: "Société needs photo library access to post Live Vibes.",
        cameraPermission: "Société needs camera access to post Live Vibes.",
      },
    ],
    [
      "expo-splash-screen",
      {
        backgroundColor: "#208AEF",
        image: "./assets/images/splash-icon.png",
        imageWidth: 76,
      },
    ],
  ],
  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },
  extra: {
    apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    // API hosts WS /v1/realtime/ws on the same host/port as REST (default :8000).
    realtimeUrl:
      process.env.EXPO_PUBLIC_REALTIME_URL ?? "ws://localhost:8000/v1/realtime/ws",
  },
});
