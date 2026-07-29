import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { canChangeDiscoverCity } from "@/features/discover/discoverPresentation";
import { noirIcons } from "@/icons/noirIcons";
import { fontFamilies } from "@/theme";

/** Shared with Discover — do not diverge for Presence. */
export const TAB_SCREEN_HORIZONTAL_PADDING = 16;
export const TAB_SCREEN_TITLE_TO_LOCATION_GAP = 4;
export const TAB_SCREEN_HEADER_PADDING_TOP = 10;
export const TAB_SCREEN_TITLE_SIZE = 40;
export const TAB_SCREEN_TITLE_LINE_HEIGHT = 44;
export const TAB_SCREEN_LOCATION_SIZE = 15;
export const TAB_SCREEN_LOCATION_COLOR = "#B9F908";

type Props = {
  title: string;
  location: string;
  /** When true, renders the Discover settings gear. */
  showSettings?: boolean;
  testID?: string;
  locationTestID?: string;
};

/**
 * Exact Discover-matching tab header: Instrument Serif title + lime city.
 */
export function TabScreenHeader({
  title,
  location,
  showSettings = false,
  testID,
  locationTestID,
}: Props) {
  const router = useRouter();
  const citySelectable = canChangeDiscoverCity();

  return (
    <View style={styles.header} testID={testID}>
      <View style={styles.headerText}>
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
        <View style={styles.cityRow} testID={locationTestID}>
          <Text style={styles.city} numberOfLines={1}>
            {location}
          </Text>
          {citySelectable ? (
            <Image
              source={noirIcons.chevronDownLime}
              style={styles.cityChevron}
              contentFit="contain"
              accessibilityIgnoresInvertColors
              testID={locationTestID ? `${locationTestID}-chevron` : undefined}
            />
          ) : null}
        </View>
      </View>
      {showSettings ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Open settings"
          testID="discover-settings-button"
          onPress={() => router.push("/(tabs)/profile")}
          style={({ pressed }) => [styles.settingsButton, pressed && styles.pressed]}
        >
          <Image
            source={noirIcons.settingsWhite}
            style={styles.settingsIcon}
            contentFit="contain"
            accessibilityIgnoresInvertColors
            testID="discover-settings-icon"
          />
        </Pressable>
      ) : (
        <View style={styles.settingsSpacer} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingTop: TAB_SCREEN_HEADER_PADDING_TOP,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    backgroundColor: "#000000",
  },
  headerText: {
    flex: 1,
    gap: TAB_SCREEN_TITLE_TO_LOCATION_GAP,
  },
  title: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: TAB_SCREEN_TITLE_SIZE,
    lineHeight: TAB_SCREEN_TITLE_LINE_HEIGHT,
    fontWeight: "400",
  },
  cityRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  city: {
    color: TAB_SCREEN_LOCATION_COLOR,
    fontFamily: fontFamilies.geistMedium,
    fontSize: TAB_SCREEN_LOCATION_SIZE,
  },
  cityChevron: {
    width: 14,
    height: 14,
  },
  settingsButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#080808",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.06)",
  },
  settingsIcon: {
    width: 21,
    height: 21,
  },
  settingsSpacer: {
    width: 0,
    height: 44,
  },
  pressed: { opacity: 0.85 },
});
