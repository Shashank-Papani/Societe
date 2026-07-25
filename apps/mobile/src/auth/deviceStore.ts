import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import { scopedDeviceIdKey, scopedInstallationIdKey } from "./deviceKeys";

const LEGACY_INSTALLATION_KEY = "societe.installation_id";
const LEGACY_DEVICE_ID_KEY = "societe.device_id";
const ACTIVE_SUBJECT_KEY = "societe.active_auth_subject";

export { scopedDeviceIdKey, scopedInstallationIdKey };

type Storage = {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
  deleteItem?: (key: string) => Promise<void>;
};

async function storage(): Promise<Storage> {
  if (Platform.OS === "web") {
    const store = new Map<string, string>();
    return {
      getItem: async (key: string) => store.get(key) ?? null,
      setItem: async (key: string, value: string) => {
        store.set(key, value);
      },
      deleteItem: async (key: string) => {
        store.delete(key);
      },
    };
  }
  return {
    getItem: (key: string) => SecureStore.getItemAsync(key),
    setItem: (key: string, value: string) => SecureStore.setItemAsync(key, value),
    deleteItem: (key: string) => SecureStore.deleteItemAsync(key),
  };
}

function newUuid(): string {
  return Crypto.randomUUID();
}

/** Dev builds namespace by auth subject so Alpha/Beta never share a device. */
function shouldScopeDeviceKeys(): boolean {
  return typeof __DEV__ !== "undefined" && __DEV__;
}

export function installationIdKeyForSubject(subject: string): string {
  if (shouldScopeDeviceKeys()) {
    return scopedInstallationIdKey(subject);
  }
  return LEGACY_INSTALLATION_KEY;
}

export function deviceIdKeyForSubject(subject: string): string {
  if (shouldScopeDeviceKeys()) {
    return scopedDeviceIdKey(subject);
  }
  return LEGACY_DEVICE_ID_KEY;
}

export async function setActiveAuthSubject(subject: string): Promise<void> {
  const s = await storage();
  await s.setItem(ACTIVE_SUBJECT_KEY, subject);
}

export async function getActiveAuthSubject(): Promise<string | null> {
  const s = await storage();
  return s.getItem(ACTIVE_SUBJECT_KEY);
}

export async function clearActiveAuthSubject(): Promise<void> {
  const s = await storage();
  if (s.deleteItem) {
    await s.deleteItem(ACTIVE_SUBJECT_KEY);
  } else {
    await s.setItem(ACTIVE_SUBJECT_KEY, "");
  }
}

/**
 * Per-subject installation id in __DEV__. Production keeps the legacy unscoped key.
 *
 * Legacy unscoped installation IDs are never reused for named personas
 * (dev-user-alpha / dev-user-beta) so they cannot collide with another account.
 * For the default local-dev-user subject only, a legacy id may be migrated once
 * into the scoped key when the scoped key is empty.
 */
export async function getOrCreateInstallationId(subject: string): Promise<string> {
  const s = await storage();
  const key = installationIdKeyForSubject(subject);
  const existing = await s.getItem(key);
  if (existing) {
    return existing;
  }

  if (shouldScopeDeviceKeys() && subject === "local-dev-user") {
    const legacy = await s.getItem(LEGACY_INSTALLATION_KEY);
    if (legacy) {
      await s.setItem(key, legacy);
      return legacy;
    }
  }

  const created = newUuid();
  await s.setItem(key, created);
  return created;
}

export async function saveDeviceId(deviceId: string, subject: string): Promise<void> {
  const s = await storage();
  await s.setItem(deviceIdKeyForSubject(subject), deviceId);
  // Keep legacy key in sync only for production / unscoped path so older readers
  // still work when not using scoped keys.
  if (!shouldScopeDeviceKeys()) {
    await s.setItem(LEGACY_DEVICE_ID_KEY, deviceId);
  }
}

/**
 * Resolve the device id for the active (or provided) auth subject.
 * In __DEV__, never fall back to another persona's scoped id or a contested
 * legacy id for alpha/beta subjects.
 */
export async function getStoredDeviceId(subject?: string | null): Promise<string | null> {
  const s = await storage();
  const resolvedSubject = subject ?? (await getActiveAuthSubject());

  if (!shouldScopeDeviceKeys()) {
    return s.getItem(LEGACY_DEVICE_ID_KEY);
  }

  if (!resolvedSubject) {
    // Avoid returning a legacy id that may belong to a different persona.
    return null;
  }

  const scoped = await s.getItem(deviceIdKeyForSubject(resolvedSubject));
  if (scoped) {
    return scoped;
  }

  // One-time migration of legacy device id only for the default local subject.
  if (resolvedSubject === "local-dev-user") {
    const legacy = await s.getItem(LEGACY_DEVICE_ID_KEY);
    if (legacy) {
      await s.setItem(deviceIdKeyForSubject(resolvedSubject), legacy);
      return legacy;
    }
  }

  return null;
}

export { newUuid };
