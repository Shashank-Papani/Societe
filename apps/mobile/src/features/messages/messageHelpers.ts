/** Pure helpers for message composer / offline send (Phase 5). */

export const MESSAGE_BODY_MAX = 2000;

export function validateMessageBody(body: string): string | null {
  const trimmed = body.trim();
  if (!trimmed) {
    return "Message cannot be empty.";
  }
  if (trimmed.length > MESSAGE_BODY_MAX) {
    return `Message must be at most ${MESSAGE_BODY_MAX} characters.`;
  }
  return null;
}

export type MessageUiState =
  | "queued"
  | "sending"
  | "server_confirmed"
  | "failed_retryable"
  | "failed_permanent";

export function mapQueueStateToMessageUi(state: string): MessageUiState {
  switch (state) {
    case "queued":
      return "queued";
    case "sending":
      return "sending";
    case "server_confirmed":
    case "acknowledged":
      return "server_confirmed";
    case "failed_retryable":
      return "failed_retryable";
    case "failed_permanent":
      return "failed_permanent";
    default:
      return "queued";
  }
}

export function shouldShowAsSent(state: MessageUiState): boolean {
  return state === "server_confirmed";
}
