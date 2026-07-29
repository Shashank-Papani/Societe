import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  TAB_ACTIVE_COLOR,
  TAB_BAR_BACKGROUND,
  TAB_CONTENT_HEIGHT,
  TAB_ICON_SIZE,
  TAB_INACTIVE_COLOR,
  tabBarTotalHeight,
  tabScreenBottomPadding,
} from "./tabBar.ts";

describe("tabBar metrics", () => {
  it("defines Instagram-like compact metrics", () => {
    assert.equal(TAB_CONTENT_HEIGHT, 50);
    assert.equal(TAB_ICON_SIZE, 24);
    assert.equal(TAB_BAR_BACKGROUND, "#000000");
    assert.equal(TAB_ACTIVE_COLOR, "#B9F908");
    assert.equal(TAB_INACTIVE_COLOR, "#8FA39D");
  });

  it("computes total height and screen bottom padding", () => {
    assert.equal(tabBarTotalHeight(0), 50);
    assert.equal(tabBarTotalHeight(34), 84);
    assert.equal(tabScreenBottomPadding(34), 100);
  });
});
