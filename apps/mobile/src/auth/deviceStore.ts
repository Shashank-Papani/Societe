import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import {
  decideLegacyRawMigration,
  isSecureStoreSafeKeySegment,
  legacyRawScopedDeviceIdKey,
  legacyRawScopedInstallationIdKey,
  scopedDeviceIdKey,
  scopedInstallationIdKey,
} from "./deviceKeys";

const LEGACY_INSTALLATION_KEY = "societe.installation_id";
const LEGACY_DEVICE_ID_KEY = "societe.device_id";
const ACTIVE_SUBJECT_KEY = "societe.active_auth_subject";

type Storage = {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
  deleteItem?: (key: string) => Promise<void>;
};

type LegacyMigrationArgs = {
  subject: string;
  hashedKey: string;
  legacyRawKey: string;
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

/** Dev builds namespace by auth subject so Alpha/Beta/OTP users never share a device. */
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

// Migrate legacy raw-subject keys into hashed keys when the old key was writable.
async function readWithLegacyMigration(
  s: Storage,
  args: LegacyMigrationArgs,
): Promise<string | null> {
  const { subject, hashedKey, legacyRawKey } = args;
  const hashed = await s.getItem(hashedKey);
  // Never call SecureStore with an unsafe legacy key (email subjects).
  let legacyRaw: string | null = null;
  if (isSecureStoreSafeKeySegment(subject)) {
    legacyRaw = await s.getItem(legacyRawKey);
  }

  const decision = decideLegacyRawMigration(subject, hashed, legacyRaw);
  if (decision === "use-hashed") {
    return hashed;
  }
  if (decision === "migrate-legacy-raw" && legacyRaw) {
    await s.setItem(hashedKey, legacyRaw);
    return legacyRaw;
  }
  return null;
}

export async function setActiveAuthSubject(subject: string): Promise<void> {
  const s = await storage();
  // Subject values may include email punctuation; only keys must be SecureStore-safe.
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
 * Persist an installation id under the subject's hashed SecureStore key.
 * Used after OTP verify when the id was generated in memory for the request.
 */
export async function persistInstallationId(
  subject: string,
  installationId: string,
): Promise<void> {
  const s = await storage();
  const key = installationIdKeyForSubject(subject);
  await s.setItem(key, installationId);
  if (!shouldScopeDeviceKeys()) {
    await s.setItem(LEGACY_INSTALLATION_KEY, installationId);
  }
}

/**
 * Per-subject installation id in __DEV__. Production keeps the legacy unscoped key.
 *
 * Migration order:
 * 1. hashed scoped key
 * 2. legacy raw-subject scoped key (only if subject is SecureStore-safe)
 * 3. unscoped legacy key for local-dev-user only
 */
export async function getOrCreateInstallationId(subject: string): Promise<string> {
  const s = await storage();

  if (!shouldScopeDeviceKeys()) {
    const existing = await s.getItem(LEGACY_INSTALLATION_KEY);
    if (existing) {
      return existing;
    }
    const created = newUuid();
    await s.setItem(LEGACY_INSTALLATION_KEY, created);
    return created;
  }

  const hashedKey = scopedInstallationIdKey(subject);
  const migrated = await readWithLegacyMigration(s, {
    subject,
    hashedKey,
    legacyRawKey: legacyRawScopedInstallationIdKey(subject),
  });
  if (migrated) {
    return migrated;
  }

  if (subject === "local-dev-user") {
    const legacy = await s.getItem(LEGACY_INSTALLATION_KEY);
    if (legacy) {
      await s.setItem(hashedKey, legacy);
      return legacy;
    }
  }

  const created = newUuid();
  await s.setItem(hashedKey, created);
  return created;
}

export async function saveDeviceId(deviceId: string, subject: string): Promise<void> {
  const s = await storage();
  await s.setItem(deviceIdKeyForSubject(subject), deviceId);
  if (!shouldScopeDeviceKeys()) {
    await s.setItem(LEGACY_DEVICE_ID_KEY, deviceId);
  }
}

/**
 * Resolve the device id for the active (or provided) auth subject.
 * In __DEV__, never fall back to another persona's scoped id or a contested
 * legacy id for alpha/beta/OTP subjects.
 */
export async function getStoredDeviceId(subject?: string | null): Promise<string | null> {
  const s = await storage();
  const resolvedSubject = subject ?? (await getActiveAuthSubject());

  if (!shouldScopeDeviceKeys()) {
    return s.getItem(LEGACY_DEVICE_ID_KEY);
  }

  if (!resolvedSubject) {
    return null;
  }

  const hashedKey = scopedDeviceIdKey(resolvedSubject);
  const migrated = await readWithLegacyMigration(s, {
    subject: resolvedSubject,
    hashedKey,
    legacyRawKey: legacyRawScopedDeviceIdKey(resolvedSubject),
  });
  if (migrated) {
    return migrated;
  }

  if (resolvedSubject === "local-dev-user") {
    const legacy = await s.getItem(LEGACY_DEVICE_ID_KEY);
    if (legacy) {
      await s.setItem(hashedKey, legacy);
      return legacy;
    }
  }

  return null;
}

export { newUuid };
