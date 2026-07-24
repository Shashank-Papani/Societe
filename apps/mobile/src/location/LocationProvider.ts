/**
 * Stable location provider interface for Phase 2.
 * Default implementation uses Expo Location (foreground only).
 */
import * as Location from "expo-location";

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

export function getLocationProvider(): LocationProvider {
  return active;
}

export function setLocationProviderForTests(provider: LocationProvider): void {
  active = provider;
}
