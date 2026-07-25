/** Pure SecureStore key helpers for per-persona device IDs (no Expo imports). */

export function scopedInstallationIdKey(subject: string): string {
  return `societe.installation_id.${subject}`;
}

export function scopedDeviceIdKey(subject: string): string {
  return `societe.device_id.${subject}`;
}
