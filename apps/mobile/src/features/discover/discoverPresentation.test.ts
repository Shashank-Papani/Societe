import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  DISCOVER_FILTERS,
  categoriesForFilter,
  filterVenues,
  venueMatchesFilter,
} from "./discoverFilters.ts";
import {
  canChangeDiscoverCity,
  containsForbiddenDiscoverCopy,
  discoverSurface,
  formatCardMeta,
  formatCategoryBadge,
  formatCrowdRow,
  formatDiscoverDistance,
  formatPrimaryMetaLine,
  formatVenueTypeTitle,
  resolveDiscoverCity,
  resolveOpenState,
  resolveStatusBadge,
  truncatesVenueNameSafe,
  venueAccessibilityLabel,
} from "./discoverPresentation.ts";
import { isVenueSaved, toggleSavedVenueId } from "./savedVenuesHelpers.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(here, "../../..");

const sampleVenues = [
  {
    id: "1",
    name: "Société Neon House",
    category: "nightclub",
    city: "Los Angeles",
    region: "CA",
    distance_m: 120,
    music_tags: ["house"],
    experience_tags: ["dance"],
    is_open: true as boolean | null | undefined,
    packed_percent: 95 as number | null | undefined,
  },
  {
    id: "2",
    name: "Static Garden",
    category: "lounge",
    city: "Los Angeles",
    region: "CA",
    distance_m: 1600,
    music_tags: ["latin"],
    experience_tags: ["relaxing"],
    is_open: false as boolean | null | undefined,
  },
  {
    id: "3",
    name: "Velvet Signal",
    category: "live_music",
    city: "Pasadena",
    region: "CA",
    distance_m: 4000,
    music_tags: ["rnb"],
    experience_tags: ["live_set"],
    crowd_label: "High Energy",
  },
];

describe("City heading uses real current data", () => {
  it("picks the dominant city from venue results", () => {
    assert.equal(resolveDiscoverCity(sampleVenues), "Los Angeles");
  });

  it("falls back to Nearby when there are no venues", () => {
    assert.equal(resolveDiscoverCity([]), "Nearby");
  });

  it("hides city chevron when location cannot be changed", () => {
    assert.equal(canChangeDiscoverCity(), false);
  });
});

describe("Category filters", () => {
  it("renders the supported Société categories", () => {
    assert.deepEqual(
      DISCOVER_FILTERS.map((f) => f.label),
      ["All", "Clubs", "Lounges", "Rooftops", "Bars"],
    );
  });

  it("marks ALL as unconstrained", () => {
    assert.deepEqual(categoriesForFilter("all"), []);
  });

  it("selecting a filter updates venue results", () => {
    const clubs = filterVenues(sampleVenues, "nightclub");
    assert.equal(clubs.length, 1);
    assert.equal(clubs[0]?.name, "Société Neon House");
    assert.equal(venueMatchesFilter("lounge", "lounge"), true);
    assert.equal(venueMatchesFilter("bar", "lounge"), false);
  });
});

describe("Venue type + distance + open metadata", () => {
  it("maps raw categories to title case labels", () => {
    assert.equal(formatVenueTypeTitle("nightclub"), "Nightclub");
    assert.equal(formatVenueTypeTitle("club"), "Club");
    assert.equal(formatVenueTypeTitle("rooftop_bar"), "Rooftop");
    assert.equal(formatVenueTypeTitle("sports_bar"), "Sports Bar");
    assert.equal(formatVenueTypeTitle("lounge"), "Lounge");
    assert.equal(formatCategoryBadge("nightclub").label, "CLUB");
  });

  it("formats imperial distance", () => {
    assert.equal(formatDiscoverDistance(106.68), "350 ft");
    assert.equal(formatDiscoverDistance(321.8688), "0.2 mi");
    assert.equal(formatDiscoverDistance(2253.08), "1.4 mi");
    assert.equal(formatCardMeta(sampleVenues[0]!), "394 ft");
  });

  it("orders metadata as type, distance, status", () => {
    assert.equal(formatPrimaryMetaLine(sampleVenues[0]!), "Nightclub • 394 ft • Open");
    assert.equal(formatPrimaryMetaLine(sampleVenues[1]!), "Lounge • 1.0 mi • Closed");
  });

  it("renders open green and closed red helpers", () => {
    assert.equal(resolveOpenState(sampleVenues[0]!)?.tone, "open");
    assert.equal(resolveOpenState(sampleVenues[0]!)?.label, "Open");
    assert.equal(resolveOpenState(sampleVenues[1]!)?.tone, "closed");
    assert.equal(discoverSurface.open, "#63D785");
    assert.equal(discoverSurface.closed, "#FF6B6B");
  });

  it("does not fabricate unknown open state", () => {
    assert.equal(resolveOpenState(sampleVenues[2]!), null);
    assert.equal(formatPrimaryMetaLine(sampleVenues[2]!), "Live Music • 2.5 mi");
  });
});

describe("Crowd / packed data honesty", () => {
  it("renders exact packed percentage when real", () => {
    const row = formatCrowdRow(sampleVenues[0]!);
    assert.deepEqual(row, { kind: "percent", text: "95% Packed", value: 95 });
  });

  it("clamps invalid packed percentages", () => {
    assert.deepEqual(formatCrowdRow({ ...sampleVenues[0]!, packed_percent: 140 }), {
      kind: "percent",
      text: "100% Packed",
      value: 100,
    });
    assert.deepEqual(formatCrowdRow({ ...sampleVenues[0]!, packed_percent: -5 }), {
      kind: "percent",
      text: "0% Packed",
      value: 0,
    });
  });

  it("does not invent a percentage when packed data is missing", () => {
    assert.equal(
      formatCrowdRow({
        ...sampleVenues[1]!,
        packed_percent: undefined,
        crowd_label: undefined,
      }),
      null,
    );
  });

  it("renders qualitative crowd label without invented percentage", () => {
    assert.deepEqual(formatCrowdRow(sampleVenues[2]!), {
      kind: "label",
      text: "High Energy",
    });
    assert.doesNotMatch(formatCrowdRow(sampleVenues[2]!)!.text, /%/);
  });
});

describe("Saved venues helpers", () => {
  it("toggles venue ids locally", () => {
    const next = toggleSavedVenueId([], "v1");
    assert.deepEqual(next, ["v1"]);
    assert.equal(isVenueSaved(next, "v1"), true);
    assert.deepEqual(toggleSavedVenueId(next, "v1"), []);
  });
});

describe("Venue cards use real venue data", () => {
  it("maps category and distance without fake pricing or ratings", () => {
    const venue = sampleVenues[0]!;
    const label = venueAccessibilityLabel(venue);
    assert.match(label, /Société Neon House/);
    assert.match(label, /Nightclub/);
    assert.match(label, /95% Packed/);
    assert.equal(containsForbiddenDiscoverCopy(label), false);
    assert.equal(containsForbiddenDiscoverCopy("Min Spend: £1.5K"), true);
    assert.equal(containsForbiddenDiscoverCopy("★★★★★"), true);
    // Legacy helper still available for older call sites.
    assert.equal(resolveStatusBadge(venue)?.label, "NEARBY");
  });

  it("uses LIVE SET when experience_tags include live_set", () => {
    assert.equal(resolveStatusBadge(sampleVenues[2]!)?.label, "LIVE SET");
  });
});

describe("Missing image displays fallback", () => {
  it("keeps production venue fallback and category assets", () => {
    assert.equal(
      existsSync(path.join(mobileRoot, "assets/images/venue-fallback.png")),
      true,
    );
    assert.equal(
      existsSync(path.join(mobileRoot, "assets/images/venue-categories/club.jpg")),
      true,
    );
  });
});

describe("Long venue names do not break the card", () => {
  it("truncates extremely long names safely", () => {
    const long = "A".repeat(80);
    const truncated = truncatesVenueNameSafe(long, 40);
    assert.ok(truncated.length <= 40);
    assert.match(truncated, /…$/);
  });
});

describe("Discover screen wiring + redesign invariants", () => {
  it("uses black surfaces, 16/9 cards, noir icons, and real routes", () => {
    const screen = readFileSync(path.join(here, "DiscoverScreen.tsx"), "utf8");
    const card = readFileSync(path.join(here, "VenueCard.tsx"), "utf8");
    const skeleton = readFileSync(path.join(here, "DiscoverSkeleton.tsx"), "utf8");
    const icons = readFileSync(path.join(mobileRoot, "src/icons/noirIcons.ts"), "utf8");
    const tabs = readFileSync(
      path.join(mobileRoot, "src/app/(tabs)/_layout.tsx"),
      "utf8",
    );

    assert.equal(discoverSurface.page, "#000000");
    assert.equal(discoverSurface.header, "#000000");
    assert.equal(discoverSurface.search, "#151515");
    assert.equal(discoverSurface.cardAspectRatio, 16 / 9);
    assert.equal(discoverSurface.cardRadius, 16);
    assert.equal(discoverSurface.cardGap, 14);

    assert.match(screen, /FlatList/);
    assert.match(screen, /paddingBottom: bottomPad/);
    assert.match(screen, /SafeAreaView/);
    assert.match(screen, /DiscoverSkeletonList/);
    assert.match(screen, /DiscoverEmptyState/);
    assert.match(screen, /DiscoverErrorState/);
    assert.match(screen, /discoverSurface\.page/);
    assert.match(screen, /discover-search/);
    assert.match(screen, /noirIcons\.searchMuted/);
    assert.match(screen, /TabScreenHeader/);
    assert.match(screen, /showSettings/);
    const tabHeader = readFileSync(
      path.join(mobileRoot, "src/components/TabScreenHeader.tsx"),
      "utf8",
    );
    assert.match(tabHeader, /noirIcons\.settingsWhite/);
    assert.match(tabHeader, /Open settings/);
    assert.match(tabHeader, /router\.push\("\/\(tabs\)\/profile"\)/);
    assert.doesNotMatch(screen, /London/);
    assert.doesNotMatch(screen, /VIP MEMBER/);
    assert.doesNotMatch(screen, /⚙︎/);
    assert.doesNotMatch(screen, /surfaceTranslucent/);

    assert.match(card, /pathname:\s*"\/venue\/\[venueId\]"/);
    assert.match(card, /venueId:\s*venue\.id/);
    assert.match(card, /aspectRatio:\s*discoverSurface\.cardAspectRatio/);
    assert.doesNotMatch(card, /aspectRatio:\s*1[^.\d]/);
    assert.doesNotMatch(card, /NEARBY|GOLD|goldBadge|statusBadge|badgeRow/);
    assert.match(card, /venue-card-gradient-/);
    assert.match(card, /venue-name-/);
    assert.match(card, /formatPrimaryMetaSegments/);
    assert.match(card, /noirIcons\.heartOutlineWhite/);
    assert.match(card, /noirIcons\.heartFilledLime/);
    assert.match(card, /stopPropagation/);
    assert.match(card, /onToggleSaved/);
    assert.match(card, /resolveVenueDisplaySource/);
    assert.match(card, /resolveVenueIdentityImage/);
    assert.doesNotMatch(card, /design-reference/);
    assert.doesNotMatch(card, /price_band|Min Spend|★★/);

    assert.match(skeleton, /aspectRatio:\s*discoverSurface\.cardAspectRatio/);
    assert.doesNotMatch(skeleton, /height:\s*300/);

    assert.match(icons, /settings\.png/);
    assert.match(icons, /search\.png/);
    assert.match(icons, /heart-outline\.png/);
    assert.match(icons, /heart-filled\.png/);
    assert.doesNotMatch(icons, /design-reference/);

    assert.equal(
      existsSync(path.join(mobileRoot, "assets/icons/noir/png/white/48/settings.png")),
      true,
    );
    assert.equal(
      existsSync(path.join(mobileRoot, "assets/icons/noir/png/muted/48/search.png")),
      true,
    );

    assert.match(tabs, /name: "index"/);
    assert.match(tabs, /name: "presence"/);
    assert.match(tabs, /name: "experience"/);
    assert.match(tabs, /name: "connect"/);
    assert.match(tabs, /name: "profile"/);
    assert.match(tabs, /SocieteTabBar/);
    assert.match(tabs, /TAB_ACTIVE_COLOR/);
    assert.match(tabs, /tabBarShowLabel:\s*false/);
  });
});

describe("Discover header control polish", () => {
  it("uses shared horizontal padding and compact upper rhythm", () => {
    const screen = readFileSync(path.join(here, "DiscoverScreen.tsx"), "utf8");
    const card = readFileSync(path.join(here, "VenueCard.tsx"), "utf8");

    assert.match(screen, /export const DISCOVER_HORIZONTAL_PADDING = 16/);
    assert.match(screen, /export const DISCOVER_TITLE_TO_LOCATION_GAP = 4/);
    assert.match(screen, /export const DISCOVER_LOCATION_TO_SEARCH_GAP = 16/);
    assert.match(screen, /export const DISCOVER_SEARCH_TO_FILTER_GAP = DISCOVER_COMPACT_GAP/);
    assert.match(
      readFileSync(path.join(here, "discoverPresentation.ts"), "utf8"),
      /export const DISCOVER_COMPACT_GAP = 10/,
    );
    assert.match(screen, /DISCOVER_COMPACT_GAP/);
    assert.match(screen, /export const DISCOVER_FILTER_TO_CARD_GAP = 16/);
    assert.match(screen, /export const DISCOVER_SEARCH_HEIGHT = 46/);
    assert.match(screen, /export const DISCOVER_FILTER_PILL_HEIGHT = 36/);

    assert.match(screen, /paddingHorizontal:\s*DISCOVER_HORIZONTAL_PADDING/);
    assert.match(screen, /TabScreenHeader/);
    assert.match(screen, /marginTop:\s*DISCOVER_LOCATION_TO_SEARCH_GAP/);
    assert.match(screen, /marginTop:\s*DISCOVER_COMPACT_GAP/);
    assert.match(screen, /marginBottom:\s*DISCOVER_FILTER_TO_CARD_GAP/);
    assert.match(screen, /height:\s*DISCOVER_SEARCH_HEIGHT/);
    assert.match(screen, /minHeight:\s*DISCOVER_FILTER_PILL_HEIGHT/);
    assert.match(screen, /hitSlop=\{styles\.filterHitSlop\}/);
    assert.match(screen, /ListHeaderComponent=\{listHeader\}/);
    assert.match(screen, /showsHorizontalScrollIndicator=\{false\}/);
    assert.match(screen, /horizontal/);
    assert.match(screen, /tabScreenBottomPadding/);
    assert.match(screen, /discoverSurface\.cardGap/);
    assert.doesNotMatch(screen, /margin(Top|Bottom):\s*-\d/);
    assert.doesNotMatch(screen, /translateY/);
    assert.doesNotMatch(screen, /position:\s*["']absolute["']/);

    const sharedHeader = readFileSync(
      path.join(here, "../../components/TabScreenHeader.tsx"),
      "utf8",
    );
    assert.match(sharedHeader, /TAB_SCREEN_HORIZONTAL_PADDING = 16/);
    assert.match(sharedHeader, /TAB_SCREEN_TITLE_TO_LOCATION_GAP = 4/);
    assert.match(sharedHeader, /TAB_SCREEN_TITLE_SIZE = 40/);
    assert.match(sharedHeader, /TAB_SCREEN_LOCATION_COLOR = "#B9F908"/);
    assert.match(sharedHeader, /gap:\s*TAB_SCREEN_TITLE_TO_LOCATION_GAP/);
    assert.match(card, /card:\s*\{[^}]*width:\s*["']100%["']/s);
    assert.doesNotMatch(card, /card:\s*\{[^}]*position:\s*["']absolute["']/s);
    assert.match(card, /aspectRatio:\s*discoverSurface\.cardAspectRatio/);
    assert.match(card, /fontSize:\s*27/);
    assert.match(card, /venue-favorite-/);
    assert.match(card, /stopPropagation/);
  });
});

describe("Instagram-style tab bar", () => {
  it("uses a compact black icon-only bar with lime active icons", () => {
    const tabs = readFileSync(
      path.join(mobileRoot, "src/app/(tabs)/_layout.tsx"),
      "utf8",
    );
    const customBar = readFileSync(
      path.join(mobileRoot, "src/navigation/SocieteTabBar.tsx"),
      "utf8",
    );
    const tabBar = readFileSync(path.join(mobileRoot, "src/navigation/tabBar.ts"), "utf8");
    const icons = readFileSync(path.join(mobileRoot, "src/icons/noirIcons.ts"), "utf8");

    assert.match(tabBar, /TAB_CONTENT_HEIGHT = 50/);
    assert.match(tabBar, /TAB_BAR_BACKGROUND = "#000000"/);
    assert.match(tabBar, /TAB_ACTIVE_COLOR = "#B9F908"/);
    assert.match(tabBar, /TAB_INACTIVE_COLOR = "#8FA39D"/);
    assert.match(tabBar, /TAB_ICON_SIZE = 24/);
    assert.match(tabBar, /export function tabScreenBottomPadding/);

    assert.match(tabs, /tabBarShowLabel:\s*false/);
    assert.match(tabs, /tabBar=\{\(props\) =>/);
    assert.match(tabs, /SocieteTabBar/);
    assert.match(tabs, /tabBarHideOnKeyboard:\s*true/);
    assert.match(tabs, /borderRadius:\s*0/);
    assert.match(tabs, /marginHorizontal:\s*0/);
    assert.doesNotMatch(tabs, /iconCircleActive/);
    assert.doesNotMatch(tabs, /tabLabel/);
    assert.doesNotMatch(tabs, /glyph/);
    assert.doesNotMatch(tabs, /height:\s*84/);

    assert.match(customBar, /testID="societe-tab-bar"/);
    assert.match(customBar, /flex:\s*1/);
    assert.match(customBar, /TAB_ICON_SIZE/);
    assert.match(customBar, /width:\s*TAB_ICON_SIZE/);
    assert.match(customBar, /height:\s*TAB_ICON_SIZE/);
    assert.match(customBar, /noirIcons\.discoverLime/);
    assert.match(customBar, /noirIcons\.presenceLime/);
    assert.match(customBar, /profileAvatarUrl/);
    assert.match(customBar, /connectHasUnread/);
    assert.match(customBar, /accessibilityRole="tab"/);
    assert.doesNotMatch(customBar, /translateY/);
    assert.doesNotMatch(customBar, /iconCircle/);
    assert.doesNotMatch(customBar, /backgroundColor:\s*colors\.lime/);
    assert.doesNotMatch(customBar, /<Text[\s>]/);

    assert.match(icons, /presenceLime/);
    assert.match(icons, /experienceMuted/);
    assert.match(icons, /connectMuted/);
    assert.match(icons, /profileLime/);
  });
});

