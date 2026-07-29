/**
 * Pure welcome-screen copy and auth-entry routing helpers (no RN imports).
 */

export const WELCOME_WORDMARK = "SOCIÉTÉ";
export const WELCOME_SUBTITLE = "THE NIGHT, LIVE";
export const WELCOME_DESCRIPTION =
  "See where the energy is building, discover the right room, and connect with the people already there.";
export const WELCOME_PRIMARY_LABEL = "ENTER SOCIÉTÉ";
export const WELCOME_SECONDARY_LABEL = "MEMBERS LOG IN";
export const WELCOME_LIME = "#B9F908";
export const WELCOME_INK = "#040907";
export const WELCOME_MUTED = "#8FA39D";

/** Production asset path relative to apps/mobile (copied from design-reference). */
export const WELCOME_BACKGROUND_ASSET_PATH = "assets/images/welcome-page-background.png";

/** Existing email OTP entry — both welcome actions use this route. */
export const WELCOME_AUTH_ROUTE = "/auth/email";

export function welcomeDisplaysNoir(wordmark: string): boolean {
  return /noir/i.test(wordmark);
}

export function resolveWelcomeAuthRoute(): typeof WELCOME_AUTH_ROUTE {
  return WELCOME_AUTH_ROUTE;
}

export type AuthGateStatus = "initializing" | "authenticated" | "unauthenticated";

/**
 * Mirrors AuthGate destination selection for unauthenticated / authenticated users.
 * Returns null when no navigation change is required.
 */
export type AuthGateDestination = "/auth" | "/onboarding" | "/";

export function resolveAuthGateDestination(params: {
  status: AuthGateStatus;
  segment0?: string | undefined;
  onboardingState?: string | null;
  meSuccess?: boolean;
}): AuthGateDestination | null {
  if (params.status === "initializing") {
    return null;
  }

  const inAuth = params.segment0 === "auth";
  const inOnboarding = params.segment0 === "onboarding";

  if (params.status === "unauthenticated") {
    if (!inAuth) {
      return "/auth";
    }
    return null;
  }

  // authenticated
  if (params.meSuccess && params.onboardingState && params.onboardingState !== "completed") {
    if (!inOnboarding) {
      return "/onboarding";
    }
    return null;
  }

  if (params.meSuccess && params.onboardingState === "completed" && (inAuth || inOnboarding)) {
    return "/";
  }

  return null;
}

export function unauthenticatedSeesWelcome(params: {
  status: AuthGateStatus;
  segment0?: string;
}): boolean {
  return (
    params.status === "unauthenticated" &&
    (params.segment0 === "auth" || resolveAuthGateDestination(params) === "/auth")
  );
}
