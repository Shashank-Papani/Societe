import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const ACCESS_KEY = "societe.access_token";
const REFRESH_KEY = "societe.refresh_token";

async function memoryFallback(): Promise<{
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
  deleteItem: (key: string) => Promise<void>;
}> {
  const store = new Map<string, string>();
  return {
    getItem: async (key) => store.get(key) ?? null,
    setItem: async (key, value) => {
      store.set(key, value);
    },
    deleteItem: async (key) => {
      store.delete(key);
    },
  };
}

async function backend() {
  if (Platform.OS === "web") {
    return memoryFallback();
  }
  return {
    getItem: (key: string) => SecureStore.getItemAsync(key),
    setItem: (key: string, value: string) => SecureStore.setItemAsync(key, value),
    deleteItem: (key: string) => SecureStore.deleteItemAsync(key),
  };
}

export async function saveAccessToken(token: string): Promise<void> {
  const b = await backend();
  await b.setItem(ACCESS_KEY, token);
}

export async function getAccessToken(): Promise<string | null> {
  const b = await backend();
  return b.getItem(ACCESS_KEY);
}

export async function clearAccessToken(): Promise<void> {
  const b = await backend();
  await b.deleteItem(ACCESS_KEY);
}

export async function saveRefreshToken(token: string): Promise<void> {
  const b = await backend();
  await b.setItem(REFRESH_KEY, token);
}

export async function getRefreshToken(): Promise<string | null> {
  const b = await backend();
  return b.getItem(REFRESH_KEY);
}

export async function clearRefreshToken(): Promise<void> {
  const b = await backend();
  await b.deleteItem(REFRESH_KEY);
}

export async function clearSessionTokens(): Promise<void> {
  await clearAccessToken();
  await clearRefreshToken();
}
