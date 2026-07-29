import { Image, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { CircleButton, Eyebrow, NeonButton } from "../components";
import { colors, fonts } from "../theme";

function PackageCard({
  title,
  price,
  children,
}: {
  title: string;
  price: string;
  children: string;
}) {
  return (
    <View style={styles.package}>
      <View style={styles.packageTop}>
        <Text style={styles.packageTitle}>{title}</Text>
        <Text style={styles.packagePrice}>{price}</Text>
      </View>
      <Text style={styles.packageDescription}>{children}</Text>
    </View>
  );
}

export function VenueDetailScreen({
  onBack,
  onReserve,
}: {
  onBack: () => void;
  onReserve: () => void;
}) {
  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.hero}>
            <Image
              source={require("../../assets/aether-lounge.png")}
              resizeMode="cover"
              style={styles.heroImage}
            />
            <View style={styles.heroShade} />
            <View style={styles.heroControls}>
              <CircleButton icon="chevron-back" onPress={onBack} />
              <CircleButton icon="heart-outline" />
            </View>
          </View>

          <View style={styles.content}>
            <View style={styles.titleRow}>
              <Text style={styles.title}>Aether Lounge</Text>
              <Text style={styles.stars}>★★★★★</Text>
            </View>
            <View style={styles.openRow}>
              <Eyebrow>Open Until 4:00 AM</Eyebrow>
              <Text style={styles.separator}>•</Text>
              <Text style={styles.area}>Mayfair, London</Text>
            </View>
            <Text style={styles.description}>
              London’s premiere velvet-rope cavern. Savor rare spirits while basking in stunning
              state-of-the-art acoustic design and elite bespoke spatial curation.
            </Text>

            <Eyebrow gold>VIP Bottle Packages</Eyebrow>
            <View style={styles.packages}>
              <PackageCard title="The Obsidian Tier" price="£1,500">
                Includes 2 bottles of Dom Perignon, 1 premium Vodka, VIP booth, and dedicated host
                services.
              </PackageCard>
              <PackageCard title="Emerald Grand Private" price="£3,500">
                VIP main-stage lounge, 3 Cristal Champagnes, Magnum Cognac, private security escort.
              </PackageCard>
            </View>
          </View>
        </ScrollView>

        <View style={styles.bookingBar}>
          <View>
            <Text style={styles.bookingLabel}>TABLE RESERVATION</Text>
            <View style={styles.priceRow}>
              <Text style={styles.bookingPrice}>£1,500</Text>
              <Text style={styles.minimum}>min</Text>
            </View>
          </View>
          <NeonButton label="Reserve VIP Table" compact onPress={onReserve} />
        </View>
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
    paddingBottom: 104,
  },
  hero: {
    height: 310,
    backgroundColor: colors.panel,
  },
  heroImage: {
    width: "100%",
    height: "100%",
  },
  heroShade: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: "rgba(0,0,0,0.16)",
  },
  heroControls: {
    position: "absolute",
    left: 18,
    right: 18,
    top: 14,
    flexDirection: "row",
    justifyContent: "space-between",
  },
  content: {
    paddingHorizontal: 20,
    paddingTop: 22,
  },
  titleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: {
    flex: 1,
    color: colors.white,
    fontFamily: fonts.serif,
    fontSize: 31,
    letterSpacing: -0.5,
  },
  stars: {
    color: colors.gold,
    fontSize: 10,
    letterSpacing: 0.6,
  },
  openRow: {
    marginTop: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  separator: {
    color: colors.muted,
    fontSize: 9,
  },
  area: {
    color: colors.mutedLight,
    fontFamily: fonts.sans,
    fontSize: 10,
  },
  description: {
    marginTop: 18,
    marginBottom: 22,
    color: colors.mutedLight,
    fontFamily: fonts.sans,
    fontSize: 12,
    lineHeight: 19,
  },
  packages: {
    marginTop: 11,
    gap: 10,
  },
  package: {
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.panel,
  },
  packageTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  packageTitle: {
    color: colors.white,
    fontFamily: fonts.sansHeavy,
    fontSize: 13,
    fontWeight: "700",
  },
  packagePrice: {
    color: colors.gold,
    fontFamily: fonts.sansHeavy,
    fontSize: 17,
    fontWeight: "800",
  },
  packageDescription: {
    color: colors.mutedLight,
    fontFamily: fonts.sans,
    fontSize: 10,
    lineHeight: 16,
  },
  bookingBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    minHeight: 92,
    paddingHorizontal: 20,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    backgroundColor: "rgba(1,8,4,0.98)",
  },
  bookingLabel: {
    color: colors.muted,
    fontFamily: fonts.sansHeavy,
    fontSize: 8,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  priceRow: {
    marginTop: 3,
    flexDirection: "row",
    alignItems: "baseline",
    gap: 3,
  },
  bookingPrice: {
    color: colors.lime,
    fontFamily: fonts.sansHeavy,
    fontSize: 19,
    fontWeight: "900",
  },
  minimum: {
    color: colors.muted,
    fontSize: 9,
  },
});
