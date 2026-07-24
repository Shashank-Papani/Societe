import { useQuery } from "@tanstack/react-query";
import { Stack, useLocalSearchParams } from "expo-router";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";

import { fetchVenueDetail } from "@/features/discover/api";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function VenueDetailScreen() {
  const { venueId } = useLocalSearchParams<{ venueId: string }>();
  const detailQuery = useQuery({
    queryKey: ["venue", venueId],
    queryFn: () => fetchVenueDetail(String(venueId)),
    enabled: Boolean(venueId),
  });

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ headerShown: true, title: "Venue", headerTintColor: "#f5f7fb" }} />
      {detailQuery.isLoading ? <ActivityIndicator color="#9aa6bf" style={{ marginTop: 40 }} /> : null}
      {detailQuery.error ? (
        <Text style={styles.error}>{(detailQuery.error as Error).message}</Text>
      ) : null}
      {detailQuery.data ? (
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.name}>{detailQuery.data.name}</Text>
          <Text style={styles.meta}>
            {detailQuery.data.category} · {detailQuery.data.city}
            {detailQuery.data.region ? `, ${detailQuery.data.region}` : ""}
          </Text>
          {detailQuery.data.description ? (
            <Text style={styles.description}>{detailQuery.data.description}</Text>
          ) : null}
          {detailQuery.data.street_address ? (
            <Text style={styles.row}>{detailQuery.data.street_address}</Text>
          ) : null}
          <Text style={styles.section}>Hours</Text>
          {detailQuery.data.hours.length === 0 ? (
            <Text style={styles.row}>No hours listed</Text>
          ) : (
            detailQuery.data.hours.map((h) => (
              <Text key={`${h.weekday}-${h.opens_local}`} style={styles.row}>
                {WEEKDAYS[h.weekday] ?? h.weekday}: {h.opens_local}–
                {h.closes_local}
                {h.closes_next_day ? " (+1)" : ""}
              </Text>
            ))
          )}
          <Text style={styles.section}>Tags</Text>
          <Text style={styles.row}>
            {[...detailQuery.data.music_tags, ...detailQuery.data.experience_tags].join(" · ") ||
              "—"}
          </Text>
        </ScrollView>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#0b1220",
  },
  content: {
    padding: 20,
    gap: 8,
    paddingBottom: 48,
  },
  name: {
    color: "#f5f7fb",
    fontSize: 28,
    fontWeight: "700",
  },
  meta: {
    color: "#9aa6bf",
    fontSize: 14,
    marginBottom: 8,
  },
  description: {
    color: "#c8d0e0",
    lineHeight: 22,
    marginBottom: 8,
  },
  section: {
    color: "#f5f7fb",
    fontWeight: "600",
    marginTop: 16,
    marginBottom: 4,
  },
  row: {
    color: "#9aa6bf",
    fontSize: 14,
  },
  error: {
    color: "#f87171",
    margin: 20,
  },
});
