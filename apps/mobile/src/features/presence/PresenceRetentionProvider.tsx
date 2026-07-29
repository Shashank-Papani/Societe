import { useQuery, useQueryClient } from "@tanstack/react-query";
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { AppState, type AppStateStatus } from "react-native";

import { useAuth } from "@/auth/AuthProvider";
import { fetchPresenceMe, type PresenceSnapshot } from "@/features/presence/api";
import {
  requestBackgroundLocationPermission,
  startBackgroundRetention,
  stopBackgroundRetention,
} from "@/features/presence/backgroundPresenceTask";
import { PresenceRetentionController } from "@/features/presence/PresenceRetentionController";
import { shouldStartRetention } from "@/features/presence/presenceRetention";

type RetentionContextValue = {
  presence: PresenceSnapshot | null | undefined;
  requestBackgroundPermissionAfterVerify: (venue: {
    venueId: string;
    latitude: number;
    longitude: number;
  }) => Promise<void>;
};

const RetentionContext = createContext<RetentionContextValue>({
  presence: undefined,
  requestBackgroundPermissionAfterVerify: async () => undefined,
});

export function PresenceRetentionProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const controllerRef = useRef<PresenceRetentionController | null>(null);
  const backgroundPromptedRef = useRef<string | null>(null);

  const presenceQuery = useQuery({
    queryKey: ["presence", "me"],
    queryFn: fetchPresenceMe,
    enabled: auth.status === "authenticated",
    refetchInterval: 60_000,
  });

  if (controllerRef.current == null) {
    controllerRef.current = new PresenceRetentionController({
      getActivePresence: () =>
        queryClient.getQueryData<PresenceSnapshot>(["presence", "me"]) ?? null,
      onPresenceUpdated: (snapshot) => {
        queryClient.setQueryData(["presence", "me"], snapshot);
      },
    });
  }

  useEffect(() => {
    if (auth.status !== "authenticated") {
      controllerRef.current?.stop();
      void stopBackgroundRetention();
      return;
    }
    const presence = presenceQuery.data ?? null;
    controllerRef.current?.syncPresence(presence);

    if (shouldStartRetention(presence) && presence?.venue) {
      // Background updates are best-effort; venue coords come from last map/sync.
      // Geofence starts when requestBackgroundPermissionAfterVerify is called.
    } else {
      void stopBackgroundRetention();
    }
  }, [auth.status, presenceQuery.data]);

  useEffect(() => {
    const onChange = (next: AppStateStatus) => {
      const foreground = next === "active";
      controllerRef.current?.setAppForeground(foreground);
    };
    const sub = AppState.addEventListener("change", onChange);
    return () => {
      sub.remove();
      controllerRef.current?.stop();
      void stopBackgroundRetention();
    };
  }, []);

  const value = useMemo<RetentionContextValue>(
    () => ({
      presence: presenceQuery.data,
      requestBackgroundPermissionAfterVerify: async (venue) => {
        if (backgroundPromptedRef.current === venue.venueId) {
          return;
        }
        backgroundPromptedRef.current = venue.venueId;
        const granted = await requestBackgroundLocationPermission();
        if (granted) {
          await startBackgroundRetention(venue);
        }
      },
    }),
    [presenceQuery.data],
  );

  return <RetentionContext.Provider value={value}>{children}</RetentionContext.Provider>;
}

export function usePresenceRetention(): RetentionContextValue {
  return useContext(RetentionContext);
}
