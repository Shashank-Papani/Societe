/**
 * Shared auth session for protected queries.
 * Tokens are restored from SecureStore; 401 triggers one refresh attempt.
 */
import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { API_BASE_URL, type ApiEnvelope } from "@/api/client";
import { clearActiveAuthSubject } from "@/auth/deviceStore";
import { clearHandledNotificationResponses } from "@/features/notifications/notificationResponseDedupe";
import { unregisterCurrentDevicePushToken } from "@/features/notifications/pushRegistration";
import { clearPendingStoryUpload } from "@/features/stories/pendingStoryUpload";
import {
  clearSessionTokens,
  getAccessToken,
  getRefreshToken,
  saveAccessToken,
  saveRefreshToken,
} from "@/auth/tokenStore";

export type AuthStatus = "initializing" | "authenticated" | "unauthenticated";

type AuthContextValue = {
  status: AuthStatus;
  accessToken: string | null;
  setSession: (accessToken: string, refreshToken?: string | null) => Promise<void>;
  clearSession: () => Promise<void>;
  handleUnauthorized: () => Promise<void>;
  refreshSession: () => Promise<string | null>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const PROTECTED_QUERY_PREFIXES = [
  "me",
  "map-venues",
  "venue",
  "presence",
  "connect",
  "messages",
  "vibes",
  "stories",
  "story-group",
  "official-posts",
  "notifications",
] as const;

let liveAccessToken: string | null = null;
let unauthorizedHandler: (() => Promise<void>) | null = null;
let refreshHandler: (() => Promise<string | null>) | null = null;
let refreshInFlight: Promise<string | null> | null = null;

export function getLiveAccessToken(): string | null {
  return liveAccessToken;
}

export function getUnauthorizedHandler(): (() => Promise<void>) | null {
  return unauthorizedHandler;
}

export function getRefreshHandler(): (() => Promise<string | null>) | null {
  return refreshHandler;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("initializing");
  const [accessToken, setAccessTokenState] = useState<string | null>(null);

  const setAccessToken = useCallback((token: string | null) => {
    liveAccessToken = token;
    setAccessTokenState(token);
  }, []);

  const clearProtectedQueries = useCallback(() => {
    for (const prefix of PROTECTED_QUERY_PREFIXES) {
      queryClient.removeQueries({ queryKey: [prefix] });
    }
  }, [queryClient]);

  const clearSession = useCallback(async () => {
    // Best-effort push unregister while tokens are still valid.
    try {
      await unregisterCurrentDevicePushToken();
    } catch {
      // Local cleanup must still complete.
    }
    await clearSessionTokens();
    await clearActiveAuthSubject();
    await clearPendingStoryUpload();
    clearHandledNotificationResponses();
    setAccessToken(null);
    setStatus("unauthenticated");
    clearProtectedQueries();
  }, [clearProtectedQueries, setAccessToken]);

  const handleUnauthorized = useCallback(async () => {
    await clearSession();
  }, [clearSession]);

  const refreshSession = useCallback(async () => {
    if (refreshInFlight) {
      return refreshInFlight;
    }
    refreshInFlight = (async () => {
      const refreshToken = await getRefreshToken();
      if (!refreshToken) {
        await clearSession();
        return null;
      }
      try {
        const response = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        const body = (await response.json()) as ApiEnvelope<{
          access_token: string;
          refresh_token: string;
        }>;
        if (!response.ok || !body.data?.access_token) {
          await clearSession();
          return null;
        }
        await saveAccessToken(body.data.access_token);
        await saveRefreshToken(body.data.refresh_token);
        setAccessToken(body.data.access_token);
        setStatus("authenticated");
        return body.data.access_token;
      } catch {
        await clearSession();
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
    return refreshInFlight;
  }, [clearSession, setAccessToken]);

  useEffect(() => {
    unauthorizedHandler = handleUnauthorized;
    refreshHandler = refreshSession;
    return () => {
      unauthorizedHandler = null;
      refreshHandler = null;
    };
  }, [handleUnauthorized, refreshSession]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await getAccessToken();
      if (cancelled) {
        return;
      }
      if (token) {
        setAccessToken(token);
        setStatus("authenticated");
      } else {
        setAccessToken(null);
        setStatus("unauthenticated");
      }
    })().catch(() => {
      if (!cancelled) {
        setAccessToken(null);
        setStatus("unauthenticated");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [setAccessToken]);

  const setSession = useCallback(
    async (token: string, refreshToken?: string | null) => {
      await saveAccessToken(token);
      if (refreshToken) {
        await saveRefreshToken(refreshToken);
      }
      setAccessToken(token);
      setStatus("authenticated");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["me"] }),
        queryClient.invalidateQueries({ queryKey: ["map-venues"] }),
        queryClient.invalidateQueries({ queryKey: ["venue"] }),
        queryClient.invalidateQueries({ queryKey: ["presence"] }),
        queryClient.invalidateQueries({ queryKey: ["connect"] }),
        queryClient.invalidateQueries({ queryKey: ["messages"] }),
      ]);
    },
    [queryClient, setAccessToken],
  );

  const value = useMemo(
    () => ({
      status,
      accessToken,
      setSession,
      clearSession,
      handleUnauthorized,
      refreshSession,
    }),
    [status, accessToken, setSession, clearSession, handleUnauthorized, refreshSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
