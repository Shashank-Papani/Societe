import { Tabs } from "expo-router";

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: { backgroundColor: "#0b1220", borderTopColor: "#1e293b" },
        tabBarActiveTintColor: "#f5f7fb",
        tabBarInactiveTintColor: "#6f7c99",
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Discover" }} />
      <Tabs.Screen name="presence" options={{ title: "Presence" }} />
      <Tabs.Screen name="profile" options={{ title: "Profile" }} />
    </Tabs>
  );
}
