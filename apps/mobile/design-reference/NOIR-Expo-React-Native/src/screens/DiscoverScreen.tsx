import { Image, ImageSourcePropType, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { BottomNav, CircleButton, Eyebrow } from "../components";
import { colors, fonts } from "../theme";

type VenueCardProps = {
  image: ImageSourcePropType;
  name: string;
  area: string;
  availability: string;
  premium?: boolean;
  onPress?: () => void;
};

function VenueCard({
  image,
  name,
  area,
  availability,
  premium = false,
  onPress,
}: VenueCardProps) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}
    >
      <Image source={image} resizeMode="cover" style={styles.cardImage} />
      <View style={styles.badgeRow}>
        <View style={styles.liveBadge}>
          <View style={styles.liveDot} />
          <Text style={styles.liveBadgeText}>VIP TABLES LIVE</Text>
        </View>
        <View style={styles.glassBadge}>
          <Text style={styles.glassBadgeText}>{premium ? "PREMIUM MEMBER" : "EXCLUSIVE"}</Text>
        </View>
      </View>
      <View style={styles.cardBody}>
        <View>
          <Text style={styles.cardTitle}>{name}</Text>
          <View style={styles.locationRow}>
            <Ionicons name="location" size={12} color={colors.mutedLight} />
            <Text style={styles.location}>{area}</Text>
          </View>
        </View>
        <View style={styles.cardMeta}>
          <Text style={styles.stars}>★★★★★</Text>
          <Text style={styles.availability}>{availability}</Text>
        </View>
      </View>
    </Pressable>
  );
}

export function DiscoverScreen({ onVenue }: { onVenue: () => void }) {
  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.header}>
            <View>
              <Eyebrow>VIP Member Platinum</Eyebrow>
              <Text style={styles.city}>London, UK</Text>
            </View>
            <CircleButton icon="person-outline" />
          </View>

          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.filters}
          >
            {["ALL", "ULTRA-CLUBS", "LOUNGES", "ROOFTOPS"].map((filter, index) => (
              <View key={filter} style={[styles.filter, index === 0 && styles.filterActive]}>
                <Text style={[styles.filterText, index === 0 && styles.filterTextActive]}>
                  {filter}
                </Text>
              </View>
            ))}
          </ScrollView>

          <VenueCard
            image={require("../../assets/aether-lounge.png")}
            name="Aether Lounge"
            area="Mayfair"
            availability="Min Spend: £1.5K"
            premium
            onPress={onVenue}
          />
          <VenueCard
            image={require("../../assets/vesper-vault.png")}
            name="Vesper Vault"
            area="Chelsea"
            availability="2 Tables Left"
          />
        </ScrollView>
        <BottomNav active="discover" onDiscover={() => undefined} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.black,
  },
  container: {
    flex: 1,
  },
  scroll: {
    paddingHorizontal: 20,
    paddingTop: 18,
    paddingBottom: 22,
    gap: 16,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 2,
  },
  city: {
    marginTop: 3,
    color: colors.white,
    fontFamily: fonts.serif,
    fontSize: 29,
    letterSpacing: -0.4,
  },
  filters: {
    gap: 8,
    paddingRight: 16,
  },
  filter: {
    height: 32,
    paddingHorizontal: 14,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.panel,
  },
  filterActive: {
    backgroundColor: colors.lime,
    borderColor: colors.lime,
  },
  filterText: {
    color: colors.mutedLight,
    fontFamily: fonts.sansHeavy,
    fontSize: 9,
    fontWeight: "800",
  },
  filterTextActive: {
    color: colors.black,
  },
  card: {
    overflow: "hidden",
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.panel,
  },
  cardPressed: {
    opacity: 0.82,
    transform: [{ scale: 0.99 }],
  },
  cardImage: {
    width: "100%",
    height: 202,
    backgroundColor: colors.panelAlt,
  },
  badgeRow: {
    position: "absolute",
    top: 12,
    left: 12,
    right: 12,
    flexDirection: "row",
    justifyContent: "space-between",
  },
  liveBadge: {
    height: 24,
    paddingHorizontal: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: 12,
    backgroundColor: "rgba(3,12,7,0.78)",
    borderWidth: 1,
    borderColor: "rgba(168,255,0,0.22)",
  },
  liveDot: {
    width: 5,
    height: 5,
    borderRadius: 3,
    backgroundColor: colors.lime,
  },
  liveBadgeText: {
    color: colors.lime,
    fontFamily: fonts.sansHeavy,
    fontSize: 8,
    fontWeight: "900",
  },
  glassBadge: {
    height: 24,
    paddingHorizontal: 10,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: "rgba(3,12,7,0.78)",
    borderWidth: 1,
    borderColor: "rgba(212,175,55,0.22)",
  },
  glassBadgeText: {
    color: colors.gold,
    fontFamily: fonts.sansHeavy,
    fontSize: 8,
    fontWeight: "900",
  },
  cardBody: {
    minHeight: 86,
    paddingHorizontal: 15,
    paddingVertical: 13,
    flexDirection: "row",
    justifyContent: "space-between",
    backgroundColor: "#07130d",
  },
  cardTitle: {
    color: colors.white,
    fontFamily: fonts.serif,
    fontSize: 22,
  },
  locationRow: {
    marginTop: 6,
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
  },
  location: {
    color: colors.mutedLight,
    fontFamily: fonts.sans,
    fontSize: 10,
  },
  cardMeta: {
    alignItems: "flex-end",
    justifyContent: "space-between",
    paddingVertical: 2,
  },
  stars: {
    color: colors.gold,
    fontSize: 10,
    letterSpacing: 0.8,
  },
  availability: {
    color: colors.lime,
    fontFamily: fonts.sansHeavy,
    fontSize: 9,
    fontWeight: "800",
  },
});
