import {
  Geist_400Regular,
  Geist_500Medium,
  Geist_600SemiBold,
  Geist_700Bold,
} from "@expo-google-fonts/geist";
import { InstrumentSerif_400Regular } from "@expo-google-fonts/instrument-serif";
import { useFonts } from "expo-font";

export const fontFamilies = {
  instrumentSerif: "InstrumentSerif_400Regular",
  geistRegular: "Geist_400Regular",
  geistMedium: "Geist_500Medium",
  geistSemiBold: "Geist_600SemiBold",
  geistBold: "Geist_700Bold",
} as const;

/**
 * App-level font loader. Call once from the root layout — do not reload fonts
 * inside individual screens.
 */
export function useAppFonts(): [boolean, Error | null] {
  const [loaded, error] = useFonts({
    InstrumentSerif_400Regular,
    Geist_400Regular,
    Geist_500Medium,
    Geist_600SemiBold,
    Geist_700Bold,
  });
  return [loaded, error ?? null];
}
