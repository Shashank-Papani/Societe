/**
 * Pure realtime URL / frame helpers (no Expo imports).
 */

export function buildAuthenticateFrame(ticket: string): { type: "authenticate"; ticket: string } {
  return { type: "authenticate", ticket };
}

export function assertSafeNotificationsWsUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.searchParams.has("ticket") || parsed.searchParams.has("access_token")) {
      return false;
    }
    return parsed.pathname.endsWith("/v1/realtime/notifications");
  } catch {
    return false;
  }
}

export function notificationsWsUrlFromApiBase(apiBase: string): string {
  const wsBase = apiBase.replace(/^http/i, "ws").replace(/\/$/, "");
  return `${wsBase}/v1/realtime/notifications`;
}
