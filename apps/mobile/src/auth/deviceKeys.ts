/**
 * Pure SecureStore key helpers for subject-scoped device IDs.
 * Never embed raw emails/auth subjects in keys — hash first (SHA-256 hex).
 */

const SAFE_SEGMENT = /^[A-Za-z0-9._-]+$/;

export function isSecureStoreSafeKeySegment(segment: string): boolean {
  return segment.length > 0 && SAFE_SEGMENT.test(segment);
}

/** Legacy pre-hash key format (may be invalid for email subjects). */
export function legacyRawScopedInstallationIdKey(subject: string): string {
  return `societe.installation_id.${subject}`;
}

/** Legacy pre-hash key format (may be invalid for email subjects). */
export function legacyRawScopedDeviceIdKey(subject: string): string {
  return `societe.device_id.${subject}`;
}

/**
 * Deterministic SecureStore-safe suffix for an auth subject.
 * SHA-256 over the complete UTF-8 subject, lowercase hex (64 chars).
 */
export function subjectSecureStoreSuffix(subject: string): string {
  return sha256HexUtf8(subject);
}

export function scopedInstallationIdKey(subject: string): string {
  return `societe.installation_id.${subjectSecureStoreSuffix(subject)}`;
}

export function scopedDeviceIdKey(subject: string): string {
  return `societe.device_id.${subjectSecureStoreSuffix(subject)}`;
}

export type LegacyMigrationDecision = "use-hashed" | "migrate-legacy-raw" | "miss";

/**
 * Decide whether to use a hashed SecureStore value, migrate a legacy raw-subject
 * key, or treat as missing. Never migrates when the subject itself is not a
 * SecureStore-safe key segment (those legacy keys could not have been written).
 */
export function decideLegacyRawMigration(
  subject: string,
  hashedValue: string | null,
  legacyRawValue: string | null,
): LegacyMigrationDecision {
  if (hashedValue) {
    return "use-hashed";
  }
  if (legacyRawValue && isSecureStoreSafeKeySegment(subject)) {
    return "migrate-legacy-raw";
  }
  return "miss";
}

/**
 * Sync SHA-256 hex digest (UTF-8). Pure JS so Node tests and Metro both work
 * without `node:crypto` or Expo imports.
 */
export function sha256HexUtf8(message: string): string {
  const bytes = utf8ToBytes(message);
  const hash = sha256(bytes);
  return bytesToHex(hash);
}

function utf8ToBytes(value: string): Uint8Array {
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(value);
  }
  // Minimal fallback for unusual runtimes without TextEncoder.
  const escaped = unescape(encodeURIComponent(value));
  const out = new Uint8Array(escaped.length);
  for (let i = 0; i < escaped.length; i += 1) {
    out[i] = escaped.charCodeAt(i);
  }
  return out;
}

function bytesToHex(bytes: Uint8Array): string {
  let hex = "";
  for (let i = 0; i < bytes.length; i += 1) {
    hex += bytes[i]!.toString(16).padStart(2, "0");
  }
  return hex;
}

// SHA-256 (FIPS 180-4), compact pure implementation for mobile + node:test.
function sha256(message: Uint8Array): Uint8Array {
  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
    0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
    0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
    0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
    0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
    0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2,
  ]);

  const bitLen = message.length * 8;
  const withOne = message.length + 1;
  let paddedLen = withOne + 8;
  while (paddedLen % 64 !== 0) {
    paddedLen += 1;
  }
  const padded = new Uint8Array(paddedLen);
  padded.set(message);
  padded[message.length] = 0x80;
  const view = new DataView(padded.buffer);
  // length in bits as 64-bit big-endian; messages here are tiny so high word is 0
  view.setUint32(paddedLen - 4, bitLen >>> 0, false);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;

  const w = new Uint32Array(64);
  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      w[i] = view.getUint32(offset + i * 4, false);
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(w[i - 15]!, 7) ^ rotr(w[i - 15]!, 18) ^ (w[i - 15]! >>> 3);
      const s1 = rotr(w[i - 2]!, 17) ^ rotr(w[i - 2]!, 19) ^ (w[i - 2]! >>> 10);
      w[i] = (w[i - 16]! + s0 + w[i - 7]! + s1) >>> 0;
    }

    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;

    for (let i = 0; i < 64; i += 1) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + K[i]! + w[i]!) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;

      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  const out = new Uint8Array(32);
  const outView = new DataView(out.buffer);
  outView.setUint32(0, h0, false);
  outView.setUint32(4, h1, false);
  outView.setUint32(8, h2, false);
  outView.setUint32(12, h3, false);
  outView.setUint32(16, h4, false);
  outView.setUint32(20, h5, false);
  outView.setUint32(24, h6, false);
  outView.setUint32(28, h7, false);
  return out;
}

function rotr(value: number, bits: number): number {
  return ((value >>> bits) | (value << (32 - bits))) >>> 0;
}
