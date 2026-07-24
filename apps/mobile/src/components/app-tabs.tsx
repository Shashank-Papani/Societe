/**
 * Legacy Expo template native tabs — unused by the Phase 1+ tab router.
 */
import { Redirect } from "expo-router";

export default function AppTabs() {
  return <Redirect href="/(tabs)" />;
}
