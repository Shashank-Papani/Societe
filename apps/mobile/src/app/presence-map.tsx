import { PresenceScreen } from "@/features/presence/PresenceScreen";

/**
 * Full-screen Presence map route. Reuses the same Presence experience until a
 * dedicated immersive map SDK is wired; keeps deep-link parity with the vision.
 */
export default function PresenceMapRoute() {
  return <PresenceScreen />;
}
