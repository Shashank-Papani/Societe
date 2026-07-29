import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  WELCOME_AUTH_ROUTE,
  WELCOME_BACKGROUND_ASSET_PATH,
  WELCOME_PRIMARY_LABEL,
  WELCOME_SECONDARY_LABEL,
  WELCOME_WORDMARK,
  resolveAuthGateDestination,
  resolveWelcomeAuthRoute,
  unauthenticatedSeesWelcome,
  welcomeDisplaysNoir,
} from "./welcomeContent.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(here, "../../..");

describe("unauthenticated user sees the welcome screen", () => {
  it("routes bare unauthenticated sessions to /auth", () => {
    assert.equal(
      resolveAuthGateDestination({ status: "unauthenticated", segment0: "(tabs)" }),
      "/auth",
    );
    assert.equal(
      unauthenticatedSeesWelcome({ status: "unauthenticated", segment0: "auth" }),
      true,
    );
  });

  it("does not bounce users already inside the auth stack", () => {
    assert.equal(
      resolveAuthGateDestination({ status: "unauthenticated", segment0: "auth" }),
      null,
    );
  });
});

describe("authenticated user is routed according to existing session logic", () => {
  it("sends incomplete onboarding to /onboarding", () => {
    assert.equal(
      resolveAuthGateDestination({
        status: "authenticated",
        segment0: "auth",
        onboardingState: "profile_required",
        meSuccess: true,
      }),
      "/onboarding",
    );
  });

  it("sends completed users away from auth/onboarding to home", () => {
    assert.equal(
      resolveAuthGateDestination({
        status: "authenticated",
        segment0: "auth",
        onboardingState: "completed",
        meSuccess: true,
      }),
      "/",
    );
  });

  it("leaves completed users on tabs alone", () => {
    assert.equal(
      resolveAuthGateDestination({
        status: "authenticated",
        segment0: "(tabs)",
        onboardingState: "completed",
        meSuccess: true,
      }),
      null,
    );
  });
});

describe("local background asset", () => {
  it("is present at the production asset path", () => {
    const assetPath = path.join(mobileRoot, WELCOME_BACKGROUND_ASSET_PATH);
    assert.equal(existsSync(assetPath), true);
  });
});

describe("welcome branding copy", () => {
  it("displays SOCIÉTÉ and never NOIR", () => {
    assert.equal(WELCOME_WORDMARK, "SOCIÉTÉ");
    assert.equal(welcomeDisplaysNoir(WELCOME_WORDMARK), false);
    assert.equal(welcomeDisplaysNoir("NOIR"), true);
  });
});

describe("welcome actions route to existing auth flow", () => {
  it("Enter Société and Members Log In share /auth/email", () => {
    assert.equal(resolveWelcomeAuthRoute(), "/auth/email");
    assert.equal(WELCOME_AUTH_ROUTE, "/auth/email");
    assert.equal(WELCOME_PRIMARY_LABEL, "ENTER SOCIÉTÉ");
    assert.equal(WELCOME_SECONDARY_LABEL, "MEMBERS LOG IN");
  });
});

describe("safe-area layout remains present", () => {
  it("keeps welcome screen using SafeAreaView edges in source", async () => {
    const sourcePath = path.join(here, "WelcomeScreen.tsx");
    assert.equal(existsSync(sourcePath), true);
    const source = await import("node:fs").then((fs) =>
      fs.readFileSync(sourcePath, "utf8"),
    );
    assert.match(source, /SafeAreaView/);
    assert.match(source, /edges=\{\["top", "bottom", "left", "right"\]\}/);
    assert.match(source, /welcome-page-background\.png/);
    assert.match(source, /ImageBackground/);
    assert.doesNotMatch(source, /\bNOIR\b/);
    assert.match(source, /SOCIÉTÉ|WELCOME_WORDMARK/);
  });
});
