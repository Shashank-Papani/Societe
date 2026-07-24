/**
 * Legacy Expo template web tabs — unused by the Phase 1+ tab router.
 * Kept as a no-op so imports do not reference removed /explore routes.
 */
import { Redirect } from "expo-router";

export default function AppTabs() {
  return <Redirect href="/(tabs)" />;
}
