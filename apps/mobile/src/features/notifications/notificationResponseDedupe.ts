/**
 * Dedupes OS notification tap navigation across cold-start + listener.
 * Kept free of Auth/React imports to avoid circular dependencies.
 */

let handledResponseIds = new Set<string>();

export function wasNotificationResponseHandled(responseId: string): boolean {
  return handledResponseIds.has(responseId);
}

export function markNotificationResponseHandled(responseId: string): void {
  handledResponseIds.add(responseId);
}

export function clearHandledNotificationResponses(): void {
  handledResponseIds = new Set();
}
