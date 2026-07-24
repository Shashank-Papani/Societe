import { useColorScheme as useRNColorScheme } from "react-native";

/** Web color-scheme hook. Phase 0 uses the RN value directly. */
export function useColorScheme() {
  return useRNColorScheme() ?? "light";
}
