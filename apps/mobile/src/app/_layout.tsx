import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Stack, useRouter, useSegments, type Href } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect, useState } from "react";
import { StatusBar } from "expo-status-bar";

import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";
import { resolveAuthGateDestination } from "@/features/auth/welcomeContent";
import { ForegroundNotificationHost } from "@/features/notifications/ForegroundNotificationHost";
import { ForegroundNotificationProvider } from "@/features/notifications/ForegroundNotificationProvider";
import { NativeNotificationResponseHost } from "@/features/notifications/NativeNotificationResponseHost";
import { NotificationsProvider } from "@/features/notifications/NotificationsProvider";
import { PresenceRetentionProvider } from "@/features/presence/PresenceRetentionProvider";
// TaskManager definitions must load at app startup.
import "@/features/presence/backgroundPresenceTask";
import { useAppFonts } from "@/theme/fonts";

SplashScreen.preventAutoHideAsync().catch(() => undefined);

function AuthGate({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const segments = useSegments();
  const router = useRouter();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: auth.status === "authenticated",
    retry: false,
  });

  useEffect(() => {
    const destination = resolveAuthGateDestination({
      status: auth.status,
      segment0: segments[0],
      onboardingState: meQuery.data?.onboarding_state,
      meSuccess: meQuery.isSuccess,
    });
    if (destination) {
      router.replace(destination as Href);
    }
  }, [
    auth.status,
    meQuery.data?.onboarding_state,
    meQuery.isSuccess,
    router,
    segments,
  ]);

  return <>{children}</>;
}

export default function RootLayout() {
  const [queryClient] = useState(() => new QueryClient());
  const [fontsLoaded, fontError] = useAppFonts();

  useEffect(() => {
    if (fontsLoaded || fontError) {
      SplashScreen.hideAsync().catch(() => undefined);
    }
  }, [fontsLoaded, fontError]);

  if (!fontsLoaded && !fontError) {
    return null;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <PresenceRetentionProvider>
          <NotificationsProvider>
            <ForegroundNotificationProvider>
              <AuthGate>
                <StatusBar style="light" />
                <Stack screenOptions={{ headerShown: false }}>
                  <Stack.Screen name="(tabs)" />
                  <Stack.Screen name="auth/index" />
                  <Stack.Screen name="auth/email" />
                  <Stack.Screen name="auth/otp" />
                  <Stack.Screen name="onboarding" />
                  <Stack.Screen name="venue" options={{ headerShown: false }} />
                  <Stack.Screen name="messages" options={{ headerShown: false }} />
                  <Stack.Screen name="blocked-users" options={{ headerShown: false }} />
                  <Stack.Screen name="presence-map" options={{ headerShown: false }} />
                  <Stack.Screen name="notifications" options={{ headerShown: false }} />
                </Stack>
                <ForegroundNotificationHost />
                <NativeNotificationResponseHost />
              </AuthGate>
            </ForegroundNotificationProvider>
          </NotificationsProvider>
        </PresenceRetentionProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
