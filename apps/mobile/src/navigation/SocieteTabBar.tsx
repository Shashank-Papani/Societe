import { Image } from "expo-image";
import { Pressable, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { noirIcons } from "@/icons/noirIcons";
import {
  TAB_ACTIVE_COLOR,
  TAB_BAR_BACKGROUND,
  TAB_BAR_BORDER,
  TAB_CONTENT_HEIGHT,
  TAB_ICON_SIZE,
} from "@/navigation/tabBar";

type TabIconKey = "discover" | "presence" | "experience" | "connect" | "profile";

type TabRoute = {
  key: string;
  name: string;
  params?: object;
};

/** Minimal Expo Router tab-bar props + Société extras. */
export type SocieteTabBarProps = {
  state: {
    index: number;
    routes: TabRoute[];
  };
  descriptors: Record<
    string,
    {
      options: {
        title?: string;
        tabBarAccessibilityLabel?: string;
      };
    }
  >;
  navigation: {
    emit: (event: {
      type: "tabPress" | "tabLongPress";
      target?: string;
      canPreventDefault?: boolean;
    }) => { defaultPrevented: boolean };
    navigate: (name: string, params?: object) => void;
  };
  profileAvatarUrl?: string | null;
  connectHasUnread?: boolean;
};

const ROUTE_ICON: Record<string, TabIconKey> = {
  index: "discover",
  presence: "presence",
  experience: "experience",
  connect: "connect",
  profile: "profile",
};

const TAB_SOURCES: Record<TabIconKey, { active: number; inactive: number }> = {
  discover: { active: noirIcons.discoverLime, inactive: noirIcons.discoverMuted },
  presence: { active: noirIcons.presenceLime, inactive: noirIcons.presenceMuted },
  experience: { active: noirIcons.experienceLime, inactive: noirIcons.experienceMuted },
  connect: { active: noirIcons.connectLime, inactive: noirIcons.connectMuted },
  profile: { active: noirIcons.profileLime, inactive: noirIcons.profileMuted },
};

function isHttpUrl(value: string | null | undefined): value is string {
  return typeof value === "string" && /^https?:\/\//i.test(value.trim());
}

/**
 * Fully custom Instagram-style dark tab bar.
 * Replaces React Navigation’s default tab chrome (circles, labels, docks).
 */
export function SocieteTabBar({
  state,
  descriptors,
  navigation,
  profileAvatarUrl = null,
  connectHasUnread = false,
}: SocieteTabBarProps) {
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[
        styles.bar,
        {
          height: TAB_CONTENT_HEIGHT + insets.bottom,
          paddingBottom: insets.bottom,
        },
      ]}
      testID="societe-tab-bar"
    >
      {state.routes.map((route, index) => {
        const focused = state.index === index;
        const { options } = descriptors[route.key] ?? { options: {} };
        const label =
          typeof options.tabBarAccessibilityLabel === "string"
            ? options.tabBarAccessibilityLabel
            : typeof options.title === "string"
              ? options.title
              : route.name;
        const iconKey = ROUTE_ICON[route.name] ?? "discover";
        const sources = TAB_SOURCES[iconKey];
        const showAvatar = iconKey === "profile" && isHttpUrl(profileAvatarUrl);
        const showUnread = iconKey === "connect" && connectHasUnread;

        const onPress = () => {
          const event = navigation.emit({
            type: "tabPress",
            target: route.key,
            canPreventDefault: true,
          }) as { defaultPrevented?: boolean };
          if (!focused && !event?.defaultPrevented) {
            navigation.navigate(route.name, route.params);
          }
        };

        const onLongPress = () => {
          navigation.emit({
            type: "tabLongPress",
            target: route.key,
          });
        };

        return (
          <Pressable
            key={route.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: focused }}
            accessibilityLabel={label}
            testID={`tab-${iconKey}`}
            onPress={onPress}
            onLongPress={onLongPress}
            style={styles.item}
          >
            <View style={styles.iconHit}>
              {showAvatar ? (
                <View
                  style={[styles.avatarRing, focused && styles.avatarRingActive]}
                  testID="tab-profile-avatar"
                >
                  <Image
                    source={{ uri: profileAvatarUrl }}
                    style={styles.avatar}
                    contentFit="cover"
                    accessibilityIgnoresInvertColors
                  />
                </View>
              ) : (
                <Image
                  source={focused ? sources.active : sources.inactive}
                  style={styles.icon}
                  contentFit="contain"
                  accessibilityIgnoresInvertColors
                  testID={`tab-icon-${iconKey}-${focused ? "active" : "inactive"}`}
                />
              )}
              {showUnread ? (
                <View style={styles.unreadDot} testID="tab-connect-unread-dot" />
              ) : null}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "stretch",
    width: "100%",
    backgroundColor: TAB_BAR_BACKGROUND,
    borderTopColor: TAB_BAR_BORDER,
    borderTopWidth: StyleSheet.hairlineWidth,
    marginHorizontal: 0,
    marginBottom: 0,
    paddingHorizontal: 0,
    paddingTop: 0,
    borderRadius: 0,
    elevation: 0,
    shadowColor: "transparent",
    shadowOpacity: 0,
    shadowOffset: { width: 0, height: 0 },
    shadowRadius: 0,
  },
  item: {
    flex: 1,
    height: TAB_CONTENT_HEIGHT,
    alignItems: "center",
    justifyContent: "center",
    margin: 0,
    padding: 0,
    backgroundColor: "transparent",
  },
  iconHit: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "transparent",
  },
  icon: {
    width: TAB_ICON_SIZE,
    height: TAB_ICON_SIZE,
  },
  avatarRing: {
    width: TAB_ICON_SIZE + 4,
    height: TAB_ICON_SIZE + 4,
    borderRadius: (TAB_ICON_SIZE + 4) / 2,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.30)",
    overflow: "hidden",
    backgroundColor: "transparent",
  },
  avatarRingActive: {
    borderColor: TAB_ACTIVE_COLOR,
    borderWidth: 2,
  },
  avatar: {
    width: TAB_ICON_SIZE,
    height: TAB_ICON_SIZE,
    borderRadius: TAB_ICON_SIZE / 2,
  },
  unreadDot: {
    position: "absolute",
    top: 8,
    right: 8,
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: TAB_ACTIVE_COLOR,
  },
});
