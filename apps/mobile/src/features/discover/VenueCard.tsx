import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text } from "react-native";

import type { VenueCard } from "@/features/discover/api";

type Props = {
  venue: VenueCard;
};

export function VenueCardView({ venue }: Props) {
  const router = useRouter();
  return (
    <Pressable
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
      onPress={() => router.push(`/venue/${venue.id}`)}
    >
      <Text style={styles.name}>{venue.name}</Text>
      <Text style={styles.meta}>
        {venue.category}
        {venue.distance_m != null ? ` · ${Math.round(venue.distance_m)} m` : ""}
      </Text>
      <Text style={styles.tags}>
        {[...venue.music_tags, ...venue.experience_tags].slice(0, 4).join(" · ") || "—"}
      </Text>
      {venue.price_band != null ? (
        <Text style={styles.price}>{"$".repeat(venue.price_band)}</Text>
      ) : null}
    </Pressable>
  );
}


const styles = StyleSheet.create({
  card: {
    paddingVertical: 14,
    paddingHorizontal: 4,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#2a3548",
    gap: 4,
  },
  pressed: {
    opacity: 0.7,
  },
  name: {
    color: "#f5f7fb",
    fontSize: 17,
    fontWeight: "600",
  },
  meta: {
    color: "#9aa6bf",
    fontSize: 13,
  },
  tags: {
    color: "#6f7c99",
    fontSize: 12,
  },
  price: {
    color: "#c4b5a0",
    fontSize: 12,
    marginTop: 2,
  },
});
