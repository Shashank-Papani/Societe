/**
 * Stable location provider interface for Phase 2.
 * Default implementation uses Expo Location (foreground).
 */
import * as Location from "expo-location";

import { offsetLatLng } from "@/features/presence/presenceRetention";

export type ForegroundLocationSample = {
  latitude: number;
  longitude: number;
  horizontal_accuracy_m: number;
  altitude_m: number | null;
  speed_mps: number | null;
  observed_at: string;
  is_mock: boolean;
  provider: string;
};

export type LocationProvider = {
  readonly name: string;
  requestForegroundPermission(): Promise<boolean>;
  getCurrentSample(): Promise<ForegroundLocationSample | null>;
};

export class ExpoLocationProvider implements LocationProvider {
  readonly name = "expo-location";

  async requestForegroundPermission(): Promise<boolean> {
    const existing = await Location.getForegroundPermissionsAsync();
    if (existing.granted) {
      return true;
    }
    const asked = await Location.requestForegroundPermissionsAsync();
    return asked.granted;
  }

  async getCurrentSample(): Promise<ForegroundLocationSample | null> {
    const granted = await this.requestForegroundPermission();
    if (!granted) {
      return null;
    }
    const position = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    return {
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      horizontal_accuracy_m: position.coords.accuracy ?? 999,
      altitude_m: position.coords.altitude,
      speed_mps: position.coords.speed,
      observed_at: new Date(position.timestamp).toISOString(),
      is_mock: Boolean((position as { mocked?: boolean }).mocked),
      provider: "fused",
    };
  }
}

let active: LocationProvider = new ExpoLocationProvider();

/** __DEV__ only — when set, getCurrentSample returns this fixed reading. */
let devLocationOverride: ForegroundLocationSample | null = null;
/** Bumped whenever the fixture changes so stale async results can be ignored. */
let locationEpoch = 0;

export function getLocationEpoch(): number {
  return locationEpoch;
}

export function getLocationProvider(): LocationProvider {
  if (__DEV__ && devLocationOverride) {
    return {
      name: "dev-fixture",
      requestForegroundPermission: async () => true,
      getCurrentSample: async () => ({
        ...devLocationOverride!,
        observed_at: new Date().toISOString(),
      }),
    };
  }
  return active;
}

export function setLocationProviderForTests(provider: LocationProvider): void {
  active = provider;
}

/**
 * Development-only GPS override shared by eligibility + verify + heartbeat.
 * Cleared automatically outside __DEV__.
 */
export function setDevLocationOverride(sample: ForegroundLocationSample | null): void {
  if (!__DEV__) {
    return;
  }
  locationEpoch += 1;
  devLocationOverride = sample;
}

export type DevFixtureKind = "inside_entry" | "retention_only" | "outside_retention";

const NEON_HOUSE = { latitude: 34.0955, longitude: -118.344 };

/**
 * Deterministic development fixtures relative to a venue centroid.
 * Distances: ~30 m (entry), ~200 m (retention-only), ~300 m (outside).
 */
export function buildDevVenueFixture(
  kind: DevFixtureKind,
  origin: { latitude: number; longitude: number } = NEON_HOUSE,
): ForegroundLocationSample {
  const metersSouth =
    kind === "inside_entry" ? 30 : kind === "retention_only" ? 200 : 300;
  const point = offsetLatLng(origin, -metersSouth, 0);
  return {
    latitude: point.latitude,
    longitude: point.longitude,
    horizontal_accuracy_m: 8,
    altitude_m: null,
    speed_mps: null,
    observed_at: new Date().toISOString(),
    is_mock: true,
    provider: "simulated",
  };
}

export function applyDevVenueFixture(
  kind: DevFixtureKind,
  origin?: { latitude: number; longitude: number },
): void {
  setDevLocationOverride(buildDevVenueFixture(kind, origin));
}
