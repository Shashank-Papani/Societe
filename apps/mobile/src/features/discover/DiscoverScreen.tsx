import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from "react-native";

import { fetchMapVenues } from "@/features/discover/api";
import { VenueCardView } from "@/features/discover/VenueCard";
import { getMapProvider } from "@/maps/MapProvider";

/** Synthetic LA default for local Discover (no live GPS in Phase 1 UI). */
const DEFAULT_CENTER = { latitude: 34.0955, longitude: -118.344 };
const DEFAULT_RADIUS_M = 8000;

export function DiscoverScreen() {
  const map = getMapProvider();
  const venuesQuery = useQuery({
    queryKey: ["map-venues", DEFAULT_CENTER, DEFAULT_RADIUS_M],
    queryFn: () =>
      fetchMapVenues({
        latitude: DEFAULT_CENTER.latitude,
        longitude: DEFAULT_CENTER.longitude,
        radius_m: DEFAULT_RADIUS_M,
        limit: 30,
      }),
  });

  const pins =
    venuesQuery.data == null
      ? []
      : map.listPins(
          { center: DEFAULT_CENTER, radius_m: DEFAULT_RADIUS_M },
          venuesQuery.data.items.map((item) => ({
            id: item.id,
            title: item.name,
            category: item.category,
            distance_m: item.distance_m,
            coordinate: item.map_pin,
          })),
        );

  return (
    <View style={styles.container}>
      <Text style={styles.brand}>Société</Text>
      <Text style={styles.title}>Discover</Text>
      <Text style={styles.subtitle}>
        {map.isNativeMapAvailable
          ? "Map ready"
          : "Development map provider · venue list near synthetic LA"}
      </Text>

      {venuesQuery.isLoading ? <ActivityIndicator color="#9aa6bf" /> : null}
      {venuesQuery.error ? (
        <Text style={styles.error}>{(venuesQuery.error as Error).message}</Text>
      ) : null}

      <FlatList
        data={venuesQuery.data?.items ?? []}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <Text style={styles.pinCount}>{pins.length} pin{pins.length === 1 ? "" : "s"}</Text>
        }
        renderItem={({ item }) => <VenueCardView venue={item} />}
        ListEmptyComponent={
          !venuesQuery.isLoading ? (
            <Text style={styles.empty}>No venues in range. Seed local data, then retry.</Text>
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#0b1220",
    paddingTop: 56,
    paddingHorizontal: 20,
  },
  brand: {
    fontSize: 28,
    fontWeight: "700",
    color: "#f5f7fb",
  },
  title: {
    fontSize: 22,
    fontWeight: "600",
    color: "#f5f7fb",
    marginTop: 4,
  },
  subtitle: {
    color: "#9aa6bf",
    marginTop: 4,
    marginBottom: 12,
    fontSize: 13,
  },
  list: {
    paddingBottom: 40,
  },
  pinCount: {
    color: "#6f7c99",
    fontSize: 12,
    marginBottom: 8,
  },
  empty: {
    color: "#9aa6bf",
    marginTop: 24,
  },
  error: {
    color: "#f87171",
    marginBottom: 8,
  },
});
