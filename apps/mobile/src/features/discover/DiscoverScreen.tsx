import { Image } from "expo-image";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/auth/AuthProvider";
import { TabScreenHeader } from "@/components/TabScreenHeader";
import { fetchMapVenues } from "@/features/discover/api";
import {
  DISCOVER_FILTERS,
  categoriesForFilter,
  filterVenues,
  type DiscoverFilterKey,
} from "@/features/discover/discoverFilters";
import {
  DISCOVER_COMPACT_GAP,
  discoverSurface,
  resolveDiscoverCity,
} from "@/features/discover/discoverPresentation";
import { DiscoverEmptyState, DiscoverErrorState } from "@/features/discover/DiscoverStates";
import { DiscoverSkeletonList } from "@/features/discover/DiscoverSkeleton";
import { useSavedVenues } from "@/features/discover/savedVenues";
import { VenueCardView } from "@/features/discover/VenueCard";
import { noirIcons } from "@/icons/noirIcons";
import { tabScreenBottomPadding } from "@/navigation/tabBar";
import { colors, fontFamilies } from "@/theme";

/** Synthetic LA default for local Discover (no live GPS required for map list). */
const DEFAULT_CENTER = { latitude: 34.0955, longitude: -118.344 };
const DEFAULT_RADIUS_M = 8000;

/** Shared left inset for title, location, search, filters, and cards. */
export const DISCOVER_HORIZONTAL_PADDING = 16;
/** Discover → Los Angeles — keep in sync with TabScreenHeader. */
export const DISCOVER_TITLE_TO_LOCATION_GAP = 4;
/** Los Angeles → search field */
export const DISCOVER_LOCATION_TO_SEARCH_GAP = 16;
/** Search field → category filters (alias of shared compact gap). */
export const DISCOVER_SEARCH_TO_FILTER_GAP = DISCOVER_COMPACT_GAP;
/** Category filters → first venue card */
export const DISCOVER_FILTER_TO_CARD_GAP = 16;
export const DISCOVER_SEARCH_HEIGHT = 46;
export const DISCOVER_FILTER_PILL_HEIGHT = 36;

export function DiscoverScreen() {
  const auth = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const savedVenues = useSavedVenues();
  const [filterKey, setFilterKey] = useState<DiscoverFilterKey>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const categoryParams = categoriesForFilter(filterKey);
  const venuesQuery = useQuery({
    queryKey: ["map-venues", DEFAULT_CENTER, DEFAULT_RADIUS_M, filterKey],
    queryFn: () =>
      fetchMapVenues({
        latitude: DEFAULT_CENTER.latitude,
        longitude: DEFAULT_CENTER.longitude,
        radius_m: DEFAULT_RADIUS_M,
        limit: 30,
        categories: categoryParams.length > 0 ? categoryParams : undefined,
      }),
    enabled: auth.status === "authenticated",
  });

  const venues = useMemo(() => {
    const items = venuesQuery.data?.items ?? [];
    // Client-side guard so UI stays consistent if the API returns a broader set.
    const filtered = filterVenues(items, filterKey);
    const q = searchQuery.trim().toLowerCase();
    if (!q) {
      return filtered;
    }
    // Local name filter only — map search endpoint does not support free-text yet.
    return filtered.filter((venue) => venue.name.toLowerCase().includes(q));
  }, [venuesQuery.data?.items, filterKey, searchQuery]);

  const city = resolveDiscoverCity(venuesQuery.data?.items ?? venues);
  const bottomPad = tabScreenBottomPadding(insets.bottom);
  const showSkeleton =
    auth.status === "authenticated" && venuesQuery.isLoading && !venuesQuery.data;

  if (auth.status === "unauthenticated") {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
        <View style={styles.signedOut} testID="discover-signed-out">
          <Text style={styles.signedOutTitle}>Discover</Text>
          <Text style={styles.signedOutBody}>Sign in to load nearby venues.</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Sign in"
            style={styles.signInButton}
            onPress={() => router.push("/auth/email")}
          >
            <Text style={styles.signInText}>Sign in</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  const listHeader = (
    <View testID="discover-list-header">
      <TabScreenHeader
        title="Discover"
        location={city}
        showSettings
        showNotifications
        testID="discover-header"
        locationTestID="discover-city"
      />

      <View style={styles.searchWrap}>
        <View style={styles.searchField} testID="discover-search-field">
          <Image
            source={noirIcons.searchMuted}
            style={styles.searchIcon}
            contentFit="contain"
            accessibilityIgnoresInvertColors
            testID="discover-search-icon"
          />
          <TextInput
            accessibilityLabel="Search venues"
            testID="discover-search"
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="Search venues…"
            placeholderTextColor={discoverSurface.searchPlaceholder}
            style={styles.searchInput}
            autoCorrect={false}
            autoCapitalize="none"
            clearButtonMode="while-editing"
          />
        </View>
      </View>

      <View style={styles.filtersWrap}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.filters}
          testID="discover-filters"
        >
          {DISCOVER_FILTERS.map((filter) => {
            const selected = filter.key === filterKey;
            return (
              <Pressable
                key={filter.key}
                accessibilityRole="button"
                accessibilityState={{ selected }}
                accessibilityLabel={`Filter ${filter.label}`}
                testID={`discover-filter-${filter.key}`}
                onPress={() => setFilterKey(filter.key)}
                hitSlop={styles.filterHitSlop}
                style={[
                  styles.filterPill,
                  selected ? styles.filterPillActive : styles.filterPillInactivePad,
                ]}
              >
                <Text style={[styles.filterText, selected && styles.filterTextActive]}>
                  {filter.label}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="discover-screen">
      <FlatList
        data={venuesQuery.isError || showSkeleton ? [] : venues}
        keyExtractor={(item) => item.id}
        ListHeaderComponent={listHeader}
        contentContainerStyle={[styles.list, { paddingBottom: bottomPad }]}
        ItemSeparatorComponent={() => (
          <View style={{ height: discoverSurface.cardGap }} />
        )}
        refreshControl={
          <RefreshControl
            refreshing={venuesQuery.isRefetching && !venuesQuery.isLoading}
            onRefresh={() => void venuesQuery.refetch()}
            tintColor={colors.lime}
          />
        }
        renderItem={({ item }) => (
          <VenueCardView
            venue={item}
            saved={savedVenues.isSaved(item.id)}
            onToggleSaved={(venueId) => {
              void savedVenues.toggleSaved(venueId);
            }}
          />
        )}
        ListEmptyComponent={
          venuesQuery.isError ? (
            <DiscoverErrorState
              onRetry={() => {
                if (__DEV__) {
                  console.warn("[discover]", venuesQuery.error);
                }
                void venuesQuery.refetch();
              }}
            />
          ) : showSkeleton ? (
            <DiscoverSkeletonList />
          ) : !venuesQuery.isLoading ? (
            <DiscoverEmptyState
              onShowAll={() => setFilterKey("all")}
              onRefresh={() => void venuesQuery.refetch()}
            />
          ) : null
        }
        testID="discover-venue-list"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: discoverSurface.page,
  },
  searchWrap: {
    marginTop: DISCOVER_LOCATION_TO_SEARCH_GAP,
  },
  searchField: {
    height: DISCOVER_SEARCH_HEIGHT,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: discoverSurface.searchBorder,
    backgroundColor: discoverSurface.search,
    paddingHorizontal: 14,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  searchIcon: {
    width: 18,
    height: 18,
  },
  searchInput: {
    flex: 1,
    color: "#FFFFFF",
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
    paddingVertical: 0,
  },
  filtersWrap: {
    marginTop: DISCOVER_COMPACT_GAP,
    marginBottom: DISCOVER_FILTER_TO_CARD_GAP,
  },
  filters: {
    gap: 9,
    alignItems: "center",
  },
  filterHitSlop: {
    top: 4,
    bottom: 4,
    left: 2,
    right: 2,
  },
  filterPill: {
    minHeight: DISCOVER_FILTER_PILL_HEIGHT,
    borderRadius: 18,
    backgroundColor: discoverSurface.pillInactive,
    borderWidth: 1,
    borderColor: discoverSurface.pillInactiveBorder,
    alignItems: "center",
    justifyContent: "center",
  },
  filterPillInactivePad: {
    paddingHorizontal: 17,
  },
  filterPillActive: {
    backgroundColor: discoverSurface.lime,
    borderColor: discoverSurface.lime,
    paddingHorizontal: 20,
  },
  filterText: {
    color: discoverSurface.pillInactiveText,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 14,
  },
  filterTextActive: {
    color: "#040907",
  },
  list: {
    paddingHorizontal: DISCOVER_HORIZONTAL_PADDING,
    flexGrow: 1,
    backgroundColor: discoverSurface.page,
  },
  signedOut: {
    flex: 1,
    padding: 24,
    justifyContent: "center",
    gap: 12,
    backgroundColor: discoverSurface.page,
  },
  signedOutTitle: {
    color: "#FFFFFF",
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 40,
  },
  signedOutBody: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
  },
  signInButton: {
    marginTop: 8,
    minHeight: 48,
    borderRadius: 999,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
  },
  signInText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 15,
  },
});
