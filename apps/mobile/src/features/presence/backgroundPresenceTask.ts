/**
 * Best-effort background presence retention.
 *
 * Task definitions must live at module top-level (Expo TaskManager requirement).
 * OS timing is not guaranteed — lease/grace on the server is the safety net.
 */

import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";

import {
  BACKGROUND_DISTANCE_INTERVAL_METERS,
  BACKGROUND_HEARTBEAT_SECONDS,
  PRESENCE_BACKGROUND_LOCATION_TASK,
  PRESENCE_GEOFENCE_TASK,
  RETENTION_RADIUS_METERS,
} from "@/features/presence/presenceRetentionPolicy";
import { submitRetentionHeartbeat } from "@/features/presence/PresenceHeartbeatService";

type BackgroundVenue = {
  venueId: string;
  latitude: number;
  longitude: number;
};

let activeBackgroundVenue: BackgroundVenue | null = null;

export function setActiveBackgroundVenue(venue: BackgroundVenue | null): void {
  activeBackgroundVenue = venue;
}

export function getActiveBackgroundVenue(): BackgroundVenue | null {
  return activeBackgroundVenue;
}

TaskManager.defineTask(PRESENCE_BACKGROUND_LOCATION_TASK, async ({ data, error }) => {
  if (error) {
    return;
  }
  const venue = activeBackgroundVenue;
  if (!venue) {
    return;
  }
  const locations = (data as { locations?: Location.LocationObject[] } | null)?.locations;
  const latest = locations?.[locations.length - 1];
  if (!latest) {
    return;
  }
  // Never use production path with __DEV__ fixture accidentally in background.
  if (!__DEV__ && (latest as { mocked?: boolean }).mocked) {
    return;
  }
  try {
    await submitRetentionHeartbeat({
      sample: {
        latitude: latest.coords.latitude,
        longitude: latest.coords.longitude,
        horizontal_accuracy_m: latest.coords.accuracy ?? 999,
        altitude_m: latest.coords.altitude,
        speed_mps: latest.coords.speed,
        observed_at: new Date(latest.timestamp).toISOString(),
        is_mock: Boolean((latest as { mocked?: boolean }).mocked),
        provider: "fused",
      },
      venueId: venue.venueId,
      appState: "background",
    });
  } catch {
    // Best-effort; lease/grace covers delays.
  }
});

TaskManager.defineTask(PRESENCE_GEOFENCE_TASK, async ({ data, error }) => {
  if (error) {
    return;
  }
  const venue = activeBackgroundVenue;
  if (!venue) {
    return;
  }
  // Geofence enter/exit only requests fresh evidence — server confirms.
  try {
    const position = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    await submitRetentionHeartbeat({
      sample: {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        horizontal_accuracy_m: position.coords.accuracy ?? 999,
        altitude_m: position.coords.altitude,
        speed_mps: position.coords.speed,
        observed_at: new Date(position.timestamp).toISOString(),
        is_mock: Boolean((position as { mocked?: boolean }).mocked),
        provider: "fused",
      },
      venueId: venue.venueId,
      appState: "background",
    });
  } catch {
    // ignore
  }
  void data;
});

export async function startBackgroundRetention(venue: BackgroundVenue): Promise<boolean> {
  setActiveBackgroundVenue(venue);
  const foreground = await Location.getForegroundPermissionsAsync();
  if (!foreground.granted) {
    return false;
  }
  const background = await Location.getBackgroundPermissionsAsync();
  if (!background.granted) {
    // Foreground retention continues; do not block.
    return false;
  }

  const started = await Location.hasStartedLocationUpdatesAsync(
    PRESENCE_BACKGROUND_LOCATION_TASK,
  );
  if (!started) {
    await Location.startLocationUpdatesAsync(PRESENCE_BACKGROUND_LOCATION_TASK, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: BACKGROUND_HEARTBEAT_SECONDS * 1000,
      distanceInterval: BACKGROUND_DISTANCE_INTERVAL_METERS,
      pausesUpdatesAutomatically: true,
      showsBackgroundLocationIndicator: true,
      foregroundService: {
        notificationTitle: "Société presence",
        notificationBody: "Keeping your venue presence active while nearby.",
      },
    });
  }

  try {
    await Location.startGeofencingAsync(PRESENCE_GEOFENCE_TASK, [
      {
        identifier: venue.venueId,
        latitude: venue.latitude,
        longitude: venue.longitude,
        radius: RETENTION_RADIUS_METERS,
        notifyOnEnter: true,
        notifyOnExit: true,
      },
    ]);
  } catch {
    // Geofencing is optional best-effort.
  }
  return true;
}

export async function stopBackgroundRetention(): Promise<void> {
  setActiveBackgroundVenue(null);
  try {
    if (await Location.hasStartedLocationUpdatesAsync(PRESENCE_BACKGROUND_LOCATION_TASK)) {
      await Location.stopLocationUpdatesAsync(PRESENCE_BACKGROUND_LOCATION_TASK);
    }
  } catch {
    // ignore
  }
  try {
    if (await Location.hasStartedGeofencingAsync(PRESENCE_GEOFENCE_TASK)) {
      await Location.stopGeofencingAsync(PRESENCE_GEOFENCE_TASK);
    }
  } catch {
    // ignore
  }
}

export async function requestBackgroundLocationPermission(): Promise<boolean> {
  const foreground = await Location.getForegroundPermissionsAsync();
  if (!foreground.granted) {
    const asked = await Location.requestForegroundPermissionsAsync();
    if (!asked.granted) {
      return false;
    }
  }
  const existing = await Location.getBackgroundPermissionsAsync();
  if (existing.granted) {
    return true;
  }
  const asked = await Location.requestBackgroundPermissionsAsync();
  return asked.granted;
}
