import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const INSTALLATION_KEY = "societe.installation_id";
const DEVICE_ID_KEY = "societe.device_id";

async function storage() {
  if (Platform.OS === "web") {
    const store = new Map<string, string>();
    return {
      getItem: async (key: string) => store.get(key) ?? null,
      setItem: async (key: string, value: string) => {
        store.set(key, value);
      },
    };
  }
  return {
    getItem: (key: string) => SecureStore.getItemAsync(key),
    setItem: (key: string, value: string) => SecureStore.setItemAsync(key, value),
  };
}

function newUuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function getOrCreateInstallationId(): Promise<string> {
  const s = await storage();
  const existing = await s.getItem(INSTALLATION_KEY);
  if (existing) {
    return existing;
  }
  const created = newUuid();
  await s.setItem(INSTALLATION_KEY, created);
  return created;
}

export async function saveDeviceId(deviceId: string): Promise<void> {
  const s = await storage();
  await s.setItem(DEVICE_ID_KEY, deviceId);
}

export async function getStoredDeviceId(): Promise<string | null> {
  const s = await storage();
  return s.getItem(DEVICE_ID_KEY);
}

export { newUuid };
