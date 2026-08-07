import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

function read(rel: string): string {
  return readFileSync(path.join(mobileRoot, rel), "utf8");
}

describe("Notification UI wiring contracts", () => {
  const center = read("src/features/notifications/NotificationCenterScreen.tsx");
  const prefs = read("src/features/notifications/NotificationPreferencesScreen.tsx");
  const provider = read("src/features/notifications/NotificationsProvider.tsx");
  const realtime = read("src/features/notifications/realtime.ts");
  const push = read("src/features/notifications/pushRegistration.ts");
  const auth = read("src/auth/AuthProvider.tsx");
  const layout = read("src/app/_layout.tsx");
  const header = read("src/components/TabScreenHeader.tsx");
  const discover = read("src/features/discover/DiscoverScreen.tsx");
  const profile = read("src/features/profile/ProfileScreen.tsx");
  const appConfig = read("app.config.ts");
  const icons = read("src/icons/noirIcons.ts");
  const nativeHost = read("src/features/notifications/NativeNotificationResponseHost.tsx");

  it("wires Notification Center routes and provider", () => {
    assert.ok(existsSync(path.join(mobileRoot, "src/app/notifications/index.tsx")));
    assert.ok(existsSync(path.join(mobileRoot, "src/app/notifications/preferences.tsx")));
    assert.ok(existsSync(path.join(mobileRoot, "src/app/notifications/info.tsx")));
    assert.match(layout, /NotificationsProvider/);
    assert.match(layout, /NativeNotificationResponseHost/);
    assert.match(layout, /name="notifications"/);
  });

  it("places unread bell on Discover header", () => {
    assert.match(header, /NotificationBellButton/);
    assert.match(header, /showNotifications/);
    assert.match(discover, /showNotifications/);
    assert.match(icons, /notificationsWhite/);
  });

  it("center supports read, read-all, dismiss, pagination, and a11y unread text", () => {
    assert.match(center, /markNotificationRead/);
    assert.match(center, /markAllNotificationsRead/);
    assert.match(center, /dismissNotification/);
    assert.match(center, /fetchNextPage/);
    assert.match(center, /RefreshControl/);
    assert.match(center, /Unread/);
    assert.match(center, /occurrence_count/);
    assert.match(center, /notifications-empty/);
    assert.match(center, /notifications-retry/);
  });

  it("preferences enforce mandatory account in-app and contextual push permission", () => {
    assert.match(prefs, /isMandatoryInAppCategory/);
    assert.match(prefs, /requestPushPermission/);
    assert.match(prefs, /registerCurrentDevicePushToken/);
    assert.match(prefs, /unregisterCurrentDevicePushToken/);
    assert.match(prefs, /Open Settings/);
    assert.match(profile, /profile-notification-preferences/);
  });

  it("realtime never puts secrets in the websocket URL", () => {
    assert.match(realtime, /\/v1\/realtime\/notifications/);
    assert.match(realtime, /type: "authenticate"/);
    assert.match(realtime, /ticket = ""/);
    assert.match(realtime, /Never log the ticket/);
    assert.match(realtime, /NO query ticket \/ access_token/);
    assert.doesNotMatch(realtime, /\?ticket=/);
    assert.doesNotMatch(realtime, /\?access_token=/);
    assert.match(realtime, /socket\.send\("ping"\)/);
    assert.match(provider, /reconnectNow|isOpen/);
  });

  it("push registration never logs tokens and logout unregisters", () => {
    assert.match(push, /Never log the raw Expo push token/);
    assert.doesNotMatch(push, /console\.(log|warn|error)\([^\)]*token/);
    assert.match(auth, /"notifications"/);
    assert.match(auth, /unregisterCurrentDevicePushToken/);
    assert.match(auth, /clearHandledNotificationResponses/);
  });

  it("native tap handler validates deep links and dedupes", () => {
    assert.match(nativeHost, /parseNotificationDeepLink/);
    assert.match(nativeHost, /wasNotificationResponseHandled/);
    assert.match(nativeHost, /getLastNotificationResponseAsync/);
  });

  it("configures expo-notifications plugin only", () => {
    assert.match(appConfig, /expo-notifications/);
    assert.match(appConfig, /permission requested contextually/);
  });
});
