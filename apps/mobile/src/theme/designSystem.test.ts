import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { colors } from "./colors.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(here, "../..");

describe("Noir design system tokens", () => {
  it("defines vision color tokens", () => {
    assert.equal(colors.backgroundPrimary, "#040907");
    assert.equal(colors.neon, "#B9F908");
    assert.equal(colors.gold, "#E2B857");
    assert.equal(colors.surfaceSolid, "#0A150F");
  });

  it("keeps five tabs and avoids production design-reference imports", () => {
    const tabs = readFileSync(
      path.join(mobileRoot, "src/app/(tabs)/_layout.tsx"),
      "utf8",
    );
    assert.match(tabs, /name: "index"/);
    assert.match(tabs, /name: "presence"/);
    assert.match(tabs, /name: "experience"/);
    assert.match(tabs, /name: "connect"/);
    assert.match(tabs, /name: "profile"/);
    assert.match(tabs, /tabBarShowLabel:\s*false/);
    assert.match(tabs, /TAB_BAR_BACKGROUND/);

    const assets = readFileSync(
      path.join(mobileRoot, "src/features/venue/venueCategoryAssets.ts"),
      "utf8",
    );
    assert.doesNotMatch(assets, /design-reference/);
    assert.match(assets, /bar2\.jpg/);
  });
});

describe("Tab bar metrics helper", () => {
  it("adds content height, inset, and breathing room", async () => {
    const { TAB_CONTENT_HEIGHT, tabBarTotalHeight, tabScreenBottomPadding } = await import(
      "../navigation/tabBar.ts"
    );
    assert.equal(TAB_CONTENT_HEIGHT, 50);
    assert.equal(tabBarTotalHeight(34), 84);
    assert.equal(tabScreenBottomPadding(34), 100);
  });
});
