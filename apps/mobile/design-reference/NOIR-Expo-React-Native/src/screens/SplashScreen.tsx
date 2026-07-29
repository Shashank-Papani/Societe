import { ImageBackground, SafeAreaView, StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { NeonButton, Eyebrow } from "../components";
import { colors, fonts } from "../theme";

export function SplashScreen({ onEnter }: { onEnter: () => void }) {
  return (
    <ImageBackground
      source={require("../../assets/noir-lounge.png")}
      resizeMode="cover"
      style={styles.background}
    >
      <LinearGradient
        colors={["rgba(1,5,3,0.28)", "rgba(1,5,3,0.05)", "rgba(1,5,3,0.96)"]}
        locations={[0, 0.42, 1]}
        style={StyleSheet.absoluteFill}
      />
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <View style={styles.line} />
          <Text style={styles.logo}>NOIR</Text>
          <Eyebrow>Elite Nightlife Council</Eyebrow>
          <Text style={styles.description}>
            Unlock the keys to the city’s most coveted velvet ropes. Elite access, bespoke bottle
            service, and absolute discretion.
          </Text>
        </View>

        <View style={styles.actions}>
          <NeonButton label="Initiate Access" onPress={onEnter} />
          <Text style={styles.login}>MEMBERS LOG IN</Text>
        </View>
      </SafeAreaView>
    </ImageBackground>
  );
}

const styles = StyleSheet.create({
  background: {
    flex: 1,
    backgroundColor: colors.black,
  },
  safe: {
    flex: 1,
    justifyContent: "flex-end",
  },
  center: {
    position: "absolute",
    top: "39%",
    left: 24,
    right: 24,
    alignItems: "center",
    paddingVertical: 30,
  },
  line: {
    width: 44,
    height: 1,
    marginBottom: 15,
    backgroundColor: "rgba(168,255,0,0.6)",
  },
  logo: {
    color: colors.white,
    fontFamily: fonts.serif,
    fontSize: 66,
    lineHeight: 72,
    letterSpacing: -2,
    textShadowColor: "rgba(0,0,0,0.8)",
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 12,
  },
  description: {
    maxWidth: 330,
    marginTop: 18,
    color: "rgba(240,246,242,0.67)",
    fontFamily: fonts.sans,
    fontSize: 12,
    lineHeight: 19,
    textAlign: "center",
  },
  actions: {
    paddingHorizontal: 30,
    paddingBottom: 18,
    gap: 16,
  },
  login: {
    color: colors.mutedLight,
    fontFamily: fonts.sansHeavy,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.4,
    textAlign: "center",
  },
});
