/**
 * Shared auth session for protected queries.
 * Token is restored from SecureStore before protected queries enable.
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

import { clearActiveAuthSubject } from "@/auth/deviceStore";
import { clearAccessToken, getAccessToken, saveAccessToken } from "@/auth/tokenStore";

export type AuthStatus = "initializing" | "authenticated" | "unauthenticated";

type AuthContextValue = {
  status: AuthStatus;
  accessToken: string | null;
  setSession: (token: string) => Promise<void>;
  clearSession: () => Promise<void>;
  handleUnauthorized: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const PROTECTED_QUERY_PREFIXES = [
  "me",
  "map-venues",
  "venue",
  "presence",
  "connect",
  "messages",
] as const;

let liveAccessToken: string | null = null;
let unauthorizedHandler: (() => Promise<void>) | null = null;

export function getLiveAccessToken(): string | null {
  return liveAccessToken;
}

export function getUnauthorizedHandler(): (() => Promise<void>) | null {
  return unauthorizedHandler;
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

  const handleUnauthorized = useCallback(async () => {
    await clearAccessToken();
    await clearActiveAuthSubject();
    setAccessToken(null);
    setStatus("unauthenticated");
    clearProtectedQueries();
  }, [clearProtectedQueries, setAccessToken]);

  useEffect(() => {
    unauthorizedHandler = handleUnauthorized;
    return () => {
      unauthorizedHandler = null;
    };
  }, [handleUnauthorized]);

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
    async (token: string) => {
      await saveAccessToken(token);
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

  const clearSession = useCallback(async () => {
    await clearAccessToken();
    await clearActiveAuthSubject();
    setAccessToken(null);
    setStatus("unauthenticated");
    clearProtectedQueries();
  }, [clearProtectedQueries, setAccessToken]);

  const value = useMemo(
    () => ({
      status,
      accessToken,
      setSession,
      clearSession,
      handleUnauthorized,
    }),
    [status, accessToken, setSession, clearSession, handleUnauthorized],
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
