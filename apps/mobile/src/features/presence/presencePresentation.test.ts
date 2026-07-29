import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { formatVenueTypeTitle } from "../discover/discoverPresentation.ts";
import { formatPresenceDistance } from "./presenceEligibility.ts";
import { projectVenuePins } from "./presenceGeometry.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.join(here, "../../..");

function read(rel: string) {
  return readFileSync(path.join(mobileRoot, rel), "utf8");
}

/** Mirrors production formatPresenceMetaLine without path-alias imports. */
function formatPresenceMetaLine(input: {
  category: string;
  distance_m?: number;
  hereNowCount?: number | null;
}): string {
  const parts = [formatVenueTypeTitle(input.category)];
  const distance = formatPresenceDistance(input.distance_m);
  if (distance) {
    parts.push(distance);
  }
  if (typeof input.hereNowCount === "number" && Number.isFinite(input.hereNowCount)) {
    parts.push(`${Math.max(0, Math.round(input.hereNowCount))} here now`);
  }
  return parts.join(" • ");
}

function visiblePeopleForStack<T>(people: T[], maxVisible = 4) {
  const visible = people.slice(0, maxVisible);
  const overflow = Math.max(0, people.length - visible.length);
  return { visible, overflow };
}

describe("presencePresentation helpers", () => {
  it("formats type and distance without inventing here-now counts", () => {
    assert.equal(
      formatPresenceMetaLine({ category: "lounge", distance_m: 1609.34 }),
      "Lounge • 1.0 mi",
    );
    assert.equal(
      formatPresenceMetaLine({
        category: "lounge",
        distance_m: 1609.34,
        hereNowCount: 12,
      }),
      "Lounge • 1.0 mi • 12 here now",
    );
    assert.equal(
      formatPresenceMetaLine({
        category: "bar",
        distance_m: 20,
        hereNowCount: null,
      }),
      "Bar • < 0.1 mi",
    );
  });

  it("projects real coordinates into a map surface", () => {
    const points = projectVenuePins(
      [
        { id: "a", latitude: 34.1, longitude: -118.3 },
        { id: "b", latitude: 34.11, longitude: -118.29 },
      ],
      200,
      200,
      20,
    );
    assert.equal(points.length, 2);
    assert.ok(points[0]!.x >= 20 && points[0]!.x <= 180);
    assert.ok(points[0]!.y >= 20 && points[0]!.y <= 180);
  });

  it("stacks visible people with overflow", () => {
    const people = Array.from({ length: 6 }, (_, i) => ({ id: `u${i}` }));
    const stack = visiblePeopleForStack(people, 4);
    assert.equal(stack.visible.length, 4);
    assert.equal(stack.overflow, 2);
  });
});

describe("Presence visual redesign contracts", () => {
  const liveMap = read("src/features/presence/PresenceLiveMap.tsx");
  const screen = read("src/features/presence/PresenceScreen.tsx");
  const tabHeader = read("src/components/TabScreenHeader.tsx");
  const discover = read("src/features/discover/DiscoverScreen.tsx");
  const presentation = read("src/features/presence/presencePresentation.ts");

  it("Presence title uses the same TabScreenHeader tokens as Discover", () => {
    assert.match(discover, /TabScreenHeader/);
    assert.match(liveMap, /TabScreenHeader/);
    assert.match(liveMap, /title="Presence"/);
    assert.match(tabHeader, /TAB_SCREEN_TITLE_SIZE = 40/);
    assert.match(tabHeader, /fontFamily: fontFamilies\.instrumentSerif/);
    assert.match(tabHeader, /TAB_SCREEN_LOCATION_COLOR = "#B9F908"/);
    assert.match(tabHeader, /fontFamily: fontFamilies\.geistMedium/);
    assert.match(tabHeader, /TAB_SCREEN_LOCATION_SIZE = 15/);
  });

  it("Presence and Discover share the same horizontal inset", () => {
    assert.match(tabHeader, /TAB_SCREEN_HORIZONTAL_PADDING = 16/);
    assert.match(discover, /export const DISCOVER_HORIZONTAL_PADDING = 16/);
    assert.match(liveMap, /TAB_SCREEN_HORIZONTAL_PADDING/);
    assert.match(liveMap, /paddingHorizontal: TAB_SCREEN_HORIZONTAL_PADDING/);
  });

  it("location uses Discover lime treatment and removes the subtitle", () => {
    assert.match(liveMap, /location=\{city\}/);
    assert.doesNotMatch(liveMap, /Where the night is moving/);
    assert.doesNotMatch(screen, /Where the night is moving/);
  });

  it("story row sits compactly under the location", () => {
    assert.match(presentation, /PRESENCE_LOCATION_TO_STORIES_GAP = 16/);
    assert.match(liveMap, /PRESENCE_LOCATION_TO_STORIES_GAP/);
    assert.match(liveMap, /marginTop: PRESENCE_LOCATION_TO_STORIES_GAP/);
    assert.doesNotMatch(liveMap, /margin(Top|Bottom):\s*-\d/);
  });

  it("story names are white, two-line, fixed width", () => {
    assert.match(presentation, /PRESENCE_STORY_ITEM_WIDTH = 80/);
    assert.match(presentation, /PRESENCE_STORY_NAME_SIZE = 14/);
    assert.match(liveMap, /color: "#FFFFFF"/);
    assert.match(liveMap, /numberOfLines=\{2\}/);
    assert.match(liveMap, /ellipsizeMode="tail"/);
    assert.match(liveMap, /width: PRESENCE_STORY_ITEM_WIDTH/);
  });

  it("removes large bottom venue chips and SDK technical copy from production UI", () => {
    assert.doesNotMatch(liveMap, /listChip/);
    assert.doesNotMatch(liveMap, /Interactive map SDK is not configured/);
    assert.doesNotMatch(screen, /Interactive map SDK is not configured/);
    assert.match(liveMap, /__DEV__/);
    assert.match(liveMap, /Nearby venues/);
  });

  it("map fallback uses black/neutral surface with projected pins", () => {
    assert.match(presentation, /map: "#0C0E0D"/);
    assert.match(presentation, /page: "#000000"/);
    assert.match(liveMap, /projectVenuePins/);
    assert.match(liveMap, /Open nearby venue map/);
    assert.doesNotMatch(liveMap, /fakePinText/);
    assert.doesNotMatch(liveMap, /pin\.title\.slice\(0, 1\)/);
  });

  it("selected venue card keeps image, Instrument Serif name, and metadata", () => {
    assert.match(liveMap, /presence-selected-image/);
    assert.match(liveMap, /fontFamilies\.instrumentSerif/);
    assert.match(liveMap, /fontSize: 28/);
    assert.match(liveMap, /formatPresenceMetaWithDistance/);
    assert.match(liveMap, /resolveVenueDisplaySource/);
  });

  it("wires here-now only through truthful helper input", () => {
    assert.match(screen, /hereNowCount=\{null\}/);
    assert.match(presentation, /hereNowCount/);
    assert.doesNotMatch(liveMap, /142 here now/);
  });

  it("gates avatar stack behind verified presence and discoverable users", () => {
    assert.match(screen, /fetchDiscoverableUsers/);
    assert.match(screen, /verifiedAtSelected/);
    assert.match(liveMap, /verifiedAtSelected \? visiblePeopleForStack/);
    assert.match(liveMap, /presence-avatar-stack/);
  });

  it("wires Verify Presence, Venue, and See who’s there actions", () => {
    assert.match(liveMap, /presence-verify-selected/);
    assert.match(liveMap, /presence-venue-button/);
    assert.match(liveMap, /presence-see-whos-there/);
    assert.match(liveMap, /See who’s there/);
    assert.match(screen, /useVerifyPresence/);
    assert.match(screen, /onOpenVenue=\{\(venueId\) => router\.push\(`\/venue\/\$\{venueId\}`\)\}/);
    assert.match(screen, /onSeeWhosThere=\{\(\) => router\.push\("\/\(tabs\)\/connect"\)\}/);
    assert.match(liveMap, /Verify your presence to see who’s there/);
  });

  it("See who’s there is full width and neutral-colored", () => {
    assert.match(liveMap, /seeWhosThereBtn:/);
    assert.match(liveMap, /backgroundColor: "#000000"/);
    assert.doesNotMatch(liveMap, /seeWhosThereBtn:[\s\S]*backgroundColor: PRESENCE_SURFACE\.lime/);
  });

  it("avoids large green background boxes in Presence content", () => {
    const forbidden = [
      "rgba(20, 26, 22",
      "colors.surfaceGlass",
      "colors.backgroundSecondary",
      "colors.surfaceSolid",
      "colors.surfacePressed",
    ];
    for (const fill of forbidden) {
      assert.doesNotMatch(liveMap, new RegExp(fill.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
      assert.doesNotMatch(screen, new RegExp(fill.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
    assert.match(liveMap, /PRESENCE_SURFACE\.card/);
    assert.match(liveMap, /PRESENCE_SURFACE\.page/);
    assert.match(liveMap, /PRESENCE_SURFACE\.lime/);
  });

  it("loading, empty, and error states match the redesign", () => {
    assert.match(screen, /presence-skeleton/);
    assert.match(screen, /Couldn’t load nearby venues/);
    assert.match(screen, /No venues found nearby/);
    assert.match(screen, /Refresh your location or try another area/);
    assert.match(screen, /presence-retry/);
  });
});

function styleBlock(source: string, name: string): string {
  const start = source.indexOf(`${name}:`);
  assert.ok(start >= 0, `missing style ${name}`);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        return source.slice(open, i + 1);
      }
    }
  }
  throw new Error(`unclosed style ${name}`);
}

describe("Presence selected-card layout contracts", () => {
  const screen = read("src/features/presence/PresenceScreen.tsx");
  const liveMap = read("src/features/presence/PresenceLiveMap.tsx");
  const tabBar = read("src/navigation/tabBar.ts");
  const selectedCard = styleBlock(liveMap, "selectedCard");
  const selectedImage = styleBlock(liveMap, "selectedImage");
  const seeWhos = styleBlock(liveMap, "seeWhosThereBtn");

  it("selected venue card is content-driven without flex:1 or screen height", () => {
    assert.doesNotMatch(selectedCard, /flex:\s*1/);
    assert.doesNotMatch(selectedCard, /flexGrow:\s*1/);
    assert.doesNotMatch(selectedCard, /height:\s*["']100%["']/);
    assert.doesNotMatch(selectedCard, /Dimensions\.get/);
    assert.doesNotMatch(selectedCard, /position:\s*["']absolute["']/);
    assert.doesNotMatch(selectedCard, /bottom:\s*0/);
  });

  it("selected image uses a finite height instead of percentage fill", () => {
    assert.match(liveMap, /SELECTED_IMAGE_HEIGHT\s*=\s*112/);
    assert.match(selectedImage, /height:\s*SELECTED_IMAGE_HEIGHT/);
    assert.doesNotMatch(selectedImage, /height:\s*["']100%["']/);
  });

  it("See who’s there is inside the selected card and not absolutely positioned", () => {
    const cardBlock = liveMap.slice(
      liveMap.indexOf('testID="presence-selected-card"'),
      liveMap.indexOf("presence-empty-inline"),
    );
    assert.match(cardBlock, /presence-see-whos-there/);
    assert.match(cardBlock, /See who’s there/);
    assert.doesNotMatch(seeWhos, /position:\s*["']absolute["']/);
    assert.match(seeWhos, /width:\s*["']100%["']/);
  });

  it("applies bottom-tab clearance exactly once via contentContainerStyle", () => {
    assert.match(screen, /tabScreenBottomPadding\(insets\.bottom\)/);
    assert.match(screen, /bottomClearance=\{bottomPad\}/);
    assert.match(liveMap, /paddingBottom:\s*bottomClearance/);
    assert.doesNotMatch(screen, /flex:\s*1,\s*paddingBottom:\s*bottomPad/);
    assert.doesNotMatch(liveMap, /ListFooterComponent/);
    assert.doesNotMatch(styleBlock(liveMap, "content"), /paddingBottom:\s*24/);
    // tabScreenBottomPadding already includes inset + content height + breathing room.
    assert.match(tabBar, /tabBarTotalHeight\(bottomInset\)\s*\+\s*TAB_BAR_BREATHING_ROOM/);
  });

  it("does not render an opaque absolute black overlay over Presence content", () => {
    assert.doesNotMatch(
      liveMap,
      /position:\s*["']absolute["'][\s\S]{0,80}backgroundColor:\s*["']#000000["']/,
    );
    assert.doesNotMatch(
      screen,
      /position:\s*["']absolute["'][\s\S]{0,80}backgroundColor:\s*["']#000000["']/,
    );
  });

  it("keeps full action rows for eligible, far, and verified presentation paths", () => {
    assert.match(liveMap, /presence-verify-selected/);
    assert.match(liveMap, /presence-venue-button/);
    assert.match(liveMap, /presence-see-whos-there/);
    assert.match(screen, /presenceButtonLabel/);
    assert.match(screen, /presenceStatusHint/);
  });
});
