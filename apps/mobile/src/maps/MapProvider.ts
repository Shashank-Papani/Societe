/**
 * Phase 1 map provider abstraction.
 *
 * Only DevelopmentMapProvider is implemented. Do not add react-native-maps or
 * Mapbox SDKs unless MAPBOX_ACCESS_TOKEN (or equivalent) is configured later.
 */

export type MapCoordinate = {
  latitude: number;
  longitude: number;
};

export type MapVenuePin = {
  id: string;
  title: string;
  coordinate: MapCoordinate;
  category: string;
  distance_m?: number;
};

export type MapCamera = {
  center: MapCoordinate;
  radius_m: number;
};

export type MapProvider = {
  readonly name: string;
  /** Whether a real map SDK is wired. Phase 1 development provider is false. */
  readonly isNativeMapAvailable: boolean;
  listPins(camera: MapCamera, venues: MapVenuePin[]): MapVenuePin[];
};

/**
 * List-based map stand-in for Phase 1. Renders venue pins as data only;
 * no third-party map SDK.
 */
export class DevelopmentMapProvider implements MapProvider {
  readonly name = "development";
  readonly isNativeMapAvailable = false;

  listPins(_camera: MapCamera, venues: MapVenuePin[]): MapVenuePin[] {
    return [...venues].sort((a, b) => (a.distance_m ?? 0) - (b.distance_m ?? 0));
  }
}

let activeProvider: MapProvider = new DevelopmentMapProvider();

export function getMapProvider(): MapProvider {
  return activeProvider;
}

/** Test/helper hook — production code should use getMapProvider(). */
export function setMapProviderForTests(provider: MapProvider): void {
  activeProvider = provider;
}
