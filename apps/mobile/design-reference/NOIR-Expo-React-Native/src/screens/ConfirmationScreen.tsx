import { useState } from "react";
import { Pressable, SafeAreaView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { colors, fonts } from "../theme";

function Detail({
  label,
  value,
  right,
}: {
  label: string;
  value: string;
  right?: boolean;
}) {
  return (
    <View style={[styles.detail, right && styles.detailRight]}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

export function ConfirmationScreen({ onDone }: { onDone: () => void }) {
  const [added, setAdded] = useState(false);

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <View style={styles.successMark}>
          <Ionicons name="checkmark" size={32} color={colors.black} />
        </View>
        <Text style={styles.title}>Access Granted</Text>
        <Text style={styles.subtitle}>
          Your reservation is confirmed. Show this pass at the velvet rope.
        </Text>

        <LinearGradient
          colors={["#07150e", "#030a06"]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.pass}
        >
          <View style={styles.passHeader}>
            <Text style={styles.venue}>Aether Lounge</Text>
            <Text style={styles.tier}>OBSIDIAN VIP</Text>
          </View>

          <View style={styles.detailGrid}>
            <Detail label="DATE" value="Friday, Oct 18" />
            <Detail label="ARRIVAL TIME" value="11:30 PM" right />
            <Detail label="GUESTS" value="4 VIP Passes" />
            <Detail label="BOTTLE SERVICE" value="Dom Pérignon Suite" right />
          </View>

          <View style={styles.dashed} />
          <View style={styles.qr}>
            <Ionicons name="scan-outline" size={66} color="#0E1511" />
          </View>
          <Text style={styles.passId}>PASS ID: NOIR-8937-22</Text>
        </LinearGradient>

        <Pressable
          accessibilityRole="button"
          onPress={() => setAdded(true)}
          style={({ pressed }) => [
            styles.walletButton,
            added && styles.walletButtonAdded,
            pressed && styles.pressed,
          ]}
        >
          <Ionicons
            name={added ? "checkmark-circle" : "wallet-outline"}
            size={17}
            color={added ? colors.black : colors.white}
          />
          <Text style={[styles.walletText, added && styles.walletTextAdded]}>
            {added ? "ADDED TO WALLET" : "ADD TO APPLE WALLET"}
          </Text>
        </Pressable>
        <Pressable onPress={onDone} style={({ pressed }) => [styles.done, pressed && styles.pressed]}>
          <Text style={styles.doneText}>BACK TO DISCOVER</Text>
        </Pressable>
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
    alignItems: "center",
    paddingHorizontal: 20,
    paddingTop: 34,
    paddingBottom: 12,
  },
  successMark: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.lime,
    shadowColor: colors.lime,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.55,
    shadowRadius: 18,
    elevation: 9,
  },
  title: {
    marginTop: 24,
    color: colors.white,
    fontFamily: fonts.serif,
    fontSize: 31,
  },
  subtitle: {
    width: 230,
    marginTop: 8,
    color: colors.mutedLight,
    fontFamily: fonts.sans,
    fontSize: 11,
    lineHeight: 16,
    textAlign: "center",
  },
  pass: {
    width: "100%",
    marginTop: 28,
    paddingHorizontal: 18,
    paddingTop: 18,
    paddingBottom: 16,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.border,
  },
  passHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingBottom: 16,
  },
  venue: {
    color: colors.white,
    fontFamily: fonts.serif,
    fontSize: 22,
  },
  tier: {
    color: colors.gold,
    fontFamily: fonts.sansHeavy,
    fontSize: 8,
    fontWeight: "900",
  },
  detailGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    rowGap: 15,
  },
  detail: {
    width: "50%",
  },
  detailRight: {
    alignItems: "flex-end",
  },
  detailLabel: {
    color: colors.muted,
    fontFamily: fonts.sansHeavy,
    fontSize: 7,
    fontWeight: "800",
    letterSpacing: 0.4,
  },
  detailValue: {
    marginTop: 3,
    color: colors.white,
    fontFamily: fonts.sansHeavy,
    fontSize: 10,
    fontWeight: "700",
  },
  dashed: {
    marginTop: 18,
    marginBottom: 16,
    borderTopWidth: 1,
    borderStyle: "dashed",
    borderColor: "#294032",
  },
  qr: {
    alignSelf: "center",
    width: 112,
    height: 112,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FAFCFB",
  },
  passId: {
    marginTop: 10,
    color: colors.muted,
    fontFamily: fonts.sansHeavy,
    fontSize: 7,
    textAlign: "center",
    letterSpacing: 0.4,
  },
  walletButton: {
    width: "100%",
    height: 50,
    marginTop: 18,
    borderRadius: 25,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  walletButtonAdded: {
    backgroundColor: colors.lime,
    borderColor: colors.lime,
  },
  walletText: {
    color: colors.white,
    fontFamily: fonts.sansHeavy,
    fontSize: 10,
    fontWeight: "900",
  },
  walletTextAdded: {
    color: colors.black,
  },
  done: {
    marginTop: 14,
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  doneText: {
    color: colors.muted,
    fontFamily: fonts.sansHeavy,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.4,
  },
  pressed: {
    opacity: 0.72,
    transform: [{ scale: 0.98 }],
  },
});
