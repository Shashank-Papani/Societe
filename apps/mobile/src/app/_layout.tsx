import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect, useState } from "react";
import { StatusBar } from "expo-status-bar";

import { AuthProvider } from "@/auth/AuthProvider";

SplashScreen.preventAutoHideAsync().catch(() => undefined);

export default function RootLayout() {
  const [queryClient] = useState(() => new QueryClient());

  useEffect(() => {
    SplashScreen.hideAsync().catch(() => undefined);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <StatusBar style="light" />
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="(tabs)" />
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
      </AuthProvider>
    </QueryClientProvider>
  );
}
