import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect, useState } from "react";
import { StatusBar } from "expo-status-bar";

import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";

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
    if (auth.status === "initializing") {
      return;
    }
    const inAuth = segments[0] === "auth";
    const inOnboarding = segments[0] === "onboarding";

    if (auth.status === "unauthenticated") {
      if (!inAuth) {
        router.replace("/auth/email");
      }
      return;
    }

    const state = meQuery.data?.onboarding_state;
    if (meQuery.isSuccess && state && state !== "completed") {
      if (!inOnboarding) {
        router.replace("/onboarding");
      }
      return;
    }

    if (meQuery.isSuccess && state === "completed" && (inAuth || inOnboarding)) {
      router.replace("/");
    }
  }, [auth.status, meQuery.data?.onboarding_state, meQuery.isSuccess, router, segments]);

  return <>{children}</>;
}

export default function RootLayout() {
  const [queryClient] = useState(() => new QueryClient());

  useEffect(() => {
    SplashScreen.hideAsync().catch(() => undefined);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthGate>
          <StatusBar style="light" />
          <Stack screenOptions={{ headerShown: false }}>
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="auth/email" />
            <Stack.Screen name="auth/otp" />
            <Stack.Screen name="onboarding" />
            <Stack.Screen
              name="venue/[venueId]"
              options={{
                headerShown: true,
                title: "Venue",
                headerStyle: { backgroundColor: "#0b1220" },
              }}
            />
            <Stack.Screen
              name="messages/index"
              options={{
                headerShown: true,
                title: "Messages",
                headerStyle: { backgroundColor: "#0b1220" },
                headerTintColor: "#f5f7fb",
              }}
            />
            <Stack.Screen
              name="messages/[conversationId]"
              options={{
                headerShown: true,
                title: "Conversation",
                headerStyle: { backgroundColor: "#0b1220" },
                headerTintColor: "#f5f7fb",
              }}
            />
          </Stack>
        </AuthGate>
      </AuthProvider>
    </QueryClientProvider>
  );
}
