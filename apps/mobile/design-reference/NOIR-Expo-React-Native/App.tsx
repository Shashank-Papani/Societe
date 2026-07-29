import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { SplashScreen } from "./src/screens/SplashScreen";
import { DiscoverScreen } from "./src/screens/DiscoverScreen";
import { VenueDetailScreen } from "./src/screens/VenueDetailScreen";
import { ConfirmationScreen } from "./src/screens/ConfirmationScreen";
import { colors } from "./src/theme";

type Screen = "splash" | "discover" | "venue" | "confirmation";

export default function App() {
  const [screen, setScreen] = useState<Screen>("splash");

  return (
    <View style={styles.app}>
      <StatusBar style="light" />
      {screen === "splash" ? <SplashScreen onEnter={() => setScreen("discover")} /> : null}
      {screen === "discover" ? <DiscoverScreen onVenue={() => setScreen("venue")} /> : null}
      {screen === "venue" ? (
        <VenueDetailScreen
          onBack={() => setScreen("discover")}
          onReserve={() => setScreen("confirmation")}
        />
      ) : null}
      {screen === "confirmation" ? (
        <ConfirmationScreen onDone={() => setScreen("discover")} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  app: {
    flex: 1,
    backgroundColor: colors.black,
  },
});
