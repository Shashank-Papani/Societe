/** Extract the auth subject (`sub`) from a Societe access JWT (no verification). */

export function subjectFromAccessToken(accessToken: string): string {
  const segment = accessToken.split(".")[1];
  if (!segment) {
    throw new Error("Invalid access token.");
  }
  const json = base64UrlDecode(segment);
  let payload: { sub?: unknown };
  try {
    payload = JSON.parse(json) as { sub?: unknown };
  } catch {
    throw new Error("Invalid access token payload.");
  }
  if (typeof payload.sub !== "string" || payload.sub.length === 0) {
    throw new Error("Access token missing subject.");
  }
  return payload.sub;
}

function base64UrlDecode(segment: string): string {
  const b64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
  const binary = globalThis.atob(b64 + pad);
  // JWT payloads are JSON ASCII; keep this simple and deterministic.
  return binary;
}
