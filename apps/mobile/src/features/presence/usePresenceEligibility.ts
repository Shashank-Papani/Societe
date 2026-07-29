import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { fetchPresenceEligibility } from "@/features/presence/api";
import {
  isLocationSampleFresh,
  normalizeEligibilityReason,
  type PresenceEligibilityView,
} from "@/features/presence/presenceEligibility";
import { getLocationProvider } from "@/location/LocationProvider";

type Options = {
  venueId: string | null;
  enabled: boolean;
  /** Bumps when the __DEV__ location fixture toggles. */
  locationSourceKey?: string | number | boolean;
};

function clientFailureView(
  venueId: string,
  reason: PresenceEligibilityView["reason"],
  sample?: {
    latitude: number;
    longitude: number;
    horizontal_accuracy_m: number;
    observed_at: string;
  } | null,
): PresenceEligibilityView {
  return {
    venueId,
    eligible: false,
    reason,
    distanceMeters: null,
    allowedRadiusMeters: null,
    locationAccuracyMeters: sample?.horizontal_accuracy_m ?? null,
    observedAt: sample?.observed_at ?? null,
    userLatitude: sample?.latitude ?? null,
    userLongitude: sample?.longitude ?? null,
  };
}

/**
 * Loads server eligibility for the selected venue using the current device
 * location (or __DEV__ location override). Stale responses for a previous
 * venue id are ignored.
 */
export function usePresenceEligibility({
  venueId,
  enabled,
  locationSourceKey = "device",
}: Options) {
  const [refreshNonce, setRefreshNonce] = useState(0);
  const requestTokenRef = useRef(0);

  useEffect(() => {
    requestTokenRef.current += 1;
  }, [venueId]);

  const query = useQuery({
    queryKey: ["presence", "eligibility", venueId, refreshNonce, locationSourceKey],
    enabled: Boolean(enabled && venueId),
    staleTime: 5_000,
    refetchInterval: 20_000,
    queryFn: async (): Promise<PresenceEligibilityView> => {
      const token = ++requestTokenRef.current;
      const selectedId = venueId;
      if (!selectedId) {
        throw new Error("Missing venue");
      }

      const provider = getLocationProvider();
      const granted = await provider.requestForegroundPermission();
      if (!granted) {
        return clientFailureView(selectedId, "location_permission_denied");
      }
      let live = await provider.getCurrentSample();
      if (!live) {
        return clientFailureView(selectedId, "location_unavailable");
      }
      if (!isLocationSampleFresh(live.observed_at)) {
        const refreshed = await provider.getCurrentSample();
        if (refreshed && isLocationSampleFresh(refreshed.observed_at)) {
          live = refreshed;
        } else {
          return clientFailureView(selectedId, "location_stale", {
            latitude: live.latitude,
            longitude: live.longitude,
            horizontal_accuracy_m: live.horizontal_accuracy_m,
            observed_at: live.observed_at,
          });
        }
      }

      const sample = {
        latitude: live.latitude,
        longitude: live.longitude,
        horizontal_accuracy_m:
          Number.isFinite(live.horizontal_accuracy_m) && live.horizontal_accuracy_m > 0
            ? live.horizontal_accuracy_m
            : 8,
        observed_at: live.observed_at,
      };

      try {
        const result = await fetchPresenceEligibility({
          latitude: sample.latitude,
          longitude: sample.longitude,
          horizontal_accuracy_m: sample.horizontal_accuracy_m,
          observed_at: sample.observed_at,
          candidate_venue_id: selectedId,
        });

        // Ignore responses that arrived after the user switched story circles.
        if (token !== requestTokenRef.current || result.venue_id !== selectedId) {
          return clientFailureView(selectedId, "loading", sample);
        }

        return {
          venueId: result.venue_id,
          eligible: result.eligible,
          reason: normalizeEligibilityReason(result.reason),
          distanceMeters:
            typeof result.distance_meters === "number" ? result.distance_meters : null,
          allowedRadiusMeters:
            typeof result.allowed_radius_meters === "number"
              ? result.allowed_radius_meters
              : null,
          locationAccuracyMeters: result.location_accuracy_meters,
          observedAt: result.observed_at,
          userLatitude: sample.latitude,
          userLongitude: sample.longitude,
        };
      } catch {
        if (token !== requestTokenRef.current) {
          return clientFailureView(selectedId, "loading", sample);
        }
        return clientFailureView(selectedId, "network", sample);
      }
    },
  });

  const loading = Boolean(enabled && venueId) && (query.isLoading || query.isFetching) && !query.data;
  const view: PresenceEligibilityView | null =
    query.data && query.data.venueId === venueId
      ? query.data
      : venueId
        ? {
            venueId,
            eligible: false,
            reason: "loading",
            distanceMeters: null,
            allowedRadiusMeters: null,
            locationAccuracyMeters: null,
            observedAt: null,
            userLatitude: null,
            userLongitude: null,
          }
        : null;

  return {
    view,
    loading: loading || (view?.reason === "loading" && !query.data),
    error: query.error,
    refresh: () => setRefreshNonce((n) => n + 1),
    isFetching: query.isFetching,
  };
}
