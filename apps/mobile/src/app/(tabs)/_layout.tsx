import { useQuery } from "@tanstack/react-query";
import { Tabs } from "expo-router";
import { StyleSheet } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/auth/AuthProvider";
import { fetchMe } from "@/auth/localAuth";
import { fetchConversations } from "@/features/messages/api";
import { SocieteTabBar, type SocieteTabBarProps } from "@/navigation/SocieteTabBar";
import {
  TAB_ACTIVE_COLOR,
  TAB_BAR_BACKGROUND,
  TAB_BAR_BORDER,
  TAB_CONTENT_HEIGHT,
  TAB_INACTIVE_COLOR,
  tabBarTotalHeight,
} from "@/navigation/tabBar";

const TAB_ROUTES = [
  { name: "index", title: "Discover" },
  { name: "presence", title: "Presence" },
  { name: "experience", title: "Experience" },
  { name: "connect", title: "Connect" },
  { name: "profile", title: "Profile" },
] as const;

export default function TabsLayout() {
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const authenticated = auth.status === "authenticated";

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: authenticated,
    staleTime: 60_000,
  });

  const conversationsQuery = useQuery({
    queryKey: ["messages", "conversations", "tab-unread"],
    queryFn: () => fetchConversations(),
    enabled: authenticated,
    staleTime: 30_000,
  });

  const approvedAvatarUrl = meQuery.data?.profile_photo_url ?? null;
  const hasUnread = (conversationsQuery.data?.items ?? []).some(
    (item) => item.unread_count > 0,
  );

  return (
    <Tabs
      tabBar={(props) => (
        <SocieteTabBar
          {...({
            state: props.state,
            descriptors: props.descriptors,
            navigation: props.navigation,
            profileAvatarUrl: approvedAvatarUrl,
            connectHasUnread: hasUnread,
          } as SocieteTabBarProps)}
        />
      )}
      screenOptions={{
        headerShown: false,
        tabBarShowLabel: false,
        tabBarHideOnKeyboard: true,
        tabBarActiveTintColor: TAB_ACTIVE_COLOR,
        tabBarInactiveTintColor: TAB_INACTIVE_COLOR,
        // Fallback metrics if a screen opts out of custom tabBar.
        tabBarStyle: {
          backgroundColor: TAB_BAR_BACKGROUND,
          borderTopColor: TAB_BAR_BORDER,
          borderTopWidth: StyleSheet.hairlineWidth,
          height: tabBarTotalHeight(insets.bottom),
          paddingTop: 0,
          paddingBottom: insets.bottom,
          paddingHorizontal: 0,
          marginHorizontal: 0,
          marginBottom: 0,
          borderRadius: 0,
          elevation: 0,
          shadowColor: "transparent",
          shadowOpacity: 0,
        },
        tabBarItemStyle: {
          flex: 1,
          height: TAB_CONTENT_HEIGHT,
          padding: 0,
          margin: 0,
        },
        tabBarIconStyle: {
          margin: 0,
          padding: 0,
        },
      }}
    >
      {TAB_ROUTES.map((route) => (
        <Tabs.Screen
          key={route.name}
          name={route.name}
          options={{
            title: route.title,
            tabBarAccessibilityLabel: route.title,
          }}
        />
      ))}
    </Tabs>
  );
}

export const DISCOVER_TAB_ROUTE_NAMES = TAB_ROUTES.map((route) => route.name);
export { TAB_CONTENT_HEIGHT };
