/**
 * Pure Calling Card realtime URL helpers (no Expo imports).
 */

export function callingCardsWsUrlFromApiBase(apiBase: string): string {
  const wsBase = apiBase.replace(/^http/i, "ws").replace(/\/$/, "");
  return `${wsBase}/v1/realtime/ws`;
}

export function assertSafeCallingCardsWsUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.searchParams.has("ticket") || parsed.searchParams.has("access_token")) {
      return false;
    }
    if (parsed.search.length > 0) {
      return false;
    }
    return parsed.pathname.endsWith("/v1/realtime/ws");
  } catch {
    return false;
  }
}

export function buildCallingCardsAuthenticateFrame(ticket: string): {
  type: "authenticate";
  ticket: string;
} {
  return { type: "authenticate", ticket };
}
