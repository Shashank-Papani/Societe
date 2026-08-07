/**
 * Expo push permission + token registration (Phase 9B).
 *
 * Backend stores only token hash/suffix — remote production Expo delivery is deferred.
 * Never log the raw Expo push token.
 */

import Constants from "expo-constants";
import { Platform } from "react-native";

import { getStoredDeviceId } from "@/auth/deviceStore";
import { registerExpoPushToken, unregisterPushToken } from "./api";

export type PushPermissionState =
  | "undetermined"
  | "granted"
  | "denied"
  | "unavailable"
  | "settings_required";

type NotificationsModule = typeof import("expo-notifications");

let notificationsModule: NotificationsModule | null = null;

async function loadNotifications(): Promise<NotificationsModule | null> {
  if (notificationsModule) {
    return notificationsModule;
  }
  if (Platform.OS === "web") {
    return null;
  }
  try {
    notificationsModule = await import("expo-notifications");
    return notificationsModule;
  } catch {
    return null;
  }
}

export async function getPushPermissionState(): Promise<PushPermissionState> {
  const Notifications = await loadNotifications();
  if (!Notifications) {
    return "unavailable";
  }
  const settings = await Notifications.getPermissionsAsync();
  if (settings.granted) {
    return "granted";
  }
  if (settings.status === "denied") {
    // iOS may require opening Settings after permanent deny.
    if (settings.canAskAgain === false) {
      return "settings_required";
    }
    return "denied";
  }
  return "undetermined";
}

export async function requestPushPermission(): Promise<PushPermissionState> {
  const Notifications = await loadNotifications();
  if (!Notifications) {
    return "unavailable";
  }
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) {
    return "granted";
  }
  if (current.canAskAgain === false) {
    return "settings_required";
  }
  const requested = await Notifications.requestPermissionsAsync();
  if (requested.granted) {
    return "granted";
  }
  if (requested.canAskAgain === false) {
    return "settings_required";
  }
  return "denied";
}

async function obtainExpoPushToken(): Promise<string | null> {
  const Notifications = await loadNotifications();
  if (!Notifications) {
    return null;
  }
  // projectId helps Expo Go / EAS; optional in local builds.
  const projectId =
    (Constants.easConfig?.projectId as string | undefined) ??
    (Constants.expoConfig?.extra?.eas?.projectId as string | undefined);
  try {
    const result = projectId
      ? await Notifications.getExpoPushTokenAsync({ projectId })
      : await Notifications.getExpoPushTokenAsync();
    const token = result.data?.trim();
    return token && token.length >= 8 ? token : null;
  } catch {
    return null;
  }
}

/**
 * Register Expo push token with the backend for the current device.
 * Token is kept in memory only for the duration of this call.
 */
export async function registerCurrentDevicePushToken(): Promise<
  "registered" | "skipped" | "failed"
> {
  const permission = await getPushPermissionState();
  if (permission !== "granted") {
    return "skipped";
  }
  const deviceId = await getStoredDeviceId();
  if (!deviceId) {
    return "failed";
  }
  const token = await obtainExpoPushToken();
  if (!token) {
    return "failed";
  }
  try {
    await registerExpoPushToken(deviceId, token);
    return "registered";
  } catch {
    return "failed";
  } finally {
    // Intentionally drop local reference; do not log token.
  }
}

export async function unregisterCurrentDevicePushToken(): Promise<void> {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) {
    return;
  }
  try {
    await unregisterPushToken(deviceId);
  } catch {
    // Best-effort during logout / toggle-off.
  }
}

export async function configureForegroundNotificationHandler(): Promise<void> {
  const Notifications = await loadNotifications();
  if (!Notifications) {
    return;
  }
  await Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}
