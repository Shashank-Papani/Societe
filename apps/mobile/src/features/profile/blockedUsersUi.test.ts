import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(here, "../..");

describe("Blocked Users management", () => {
  it("exposes Blocked Users under Profile Privacy", () => {
    const profile = readFileSync(path.join(here, "ProfileScreen.tsx"), "utf8");
    assert.match(profile, /testID="profile-blocked-users"/);
    assert.match(profile, /Blocked Users/);
    assert.match(profile, /\/blocked-users/);
  });

  it("renders a dedicated blocked users screen with unblock confirmation", () => {
    const screen = readFileSync(path.join(here, "BlockedUsersScreen.tsx"), "utf8");
    assert.match(screen, /testID="blocked-users-screen"/);
    assert.match(screen, /No blocked users/);
    assert.match(screen, /People you block will appear here\./);
    assert.match(screen, /Alert\.alert/);
    assert.match(screen, /Unblock \$\{user\.display_name\}\?/);
    assert.match(screen, /fetchBlockedUsers/);
    assert.match(screen, /unblockUser/);
    assert.match(screen, /testID=\{`blocked-user-unblock-\$\{item\.user_id\}`\}/);
  });

  it("removes the row on success and keeps it on failure", () => {
    const screen = readFileSync(path.join(here, "BlockedUsersScreen.tsx"), "utf8");
    assert.match(screen, /setQueryData<BlockedUser\[]>/);
    assert.match(screen, /filter\(\(item\) => item\.user_id !== userId\)/);
    assert.match(screen, /Couldn’t unblock\. Try again\./);
    assert.match(screen, /testID="blocked-users-error"/);
  });

  it("registers the blocked-users route", () => {
    const route = readFileSync(path.join(mobileRoot, "app/blocked-users.tsx"), "utf8");
    const layout = readFileSync(path.join(mobileRoot, "app/_layout.tsx"), "utf8");
    assert.match(route, /BlockedUsersScreen/);
    assert.match(layout, /name="blocked-users"/);
  });
});
