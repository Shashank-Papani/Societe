import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

function read(rel: string): string {
  return readFileSync(path.join(mobileRoot, rel), "utf8");
}

describe("Story UI wiring contracts", () => {
  const rail = read("src/features/stories/StoryRail.tsx");
  const viewer = read("src/features/stories/StoryViewerModal.tsx");
  const composer = read("src/features/stories/StoryComposerModal.tsx");
  const posts = read("src/features/stories/OfficialPostsSection.tsx");
  const experience = read("src/features/experience/ExperienceScreen.tsx");
  const venue = read("src/features/venue/VenueDetailScreen.tsx");
  const auth = read("src/auth/AuthProvider.tsx");
  const api = read("src/features/stories/api.ts");

  it("wires Story rail + viewer + composer into Experience", () => {
    assert.match(experience, /StoryRail/);
    assert.match(experience, /StoryViewerModal/);
    assert.match(experience, /StoryComposerModal/);
    assert.match(experience, /\["stories", "experience"\]/);
    assert.match(experience, /experience-your-story/);
    assert.match(experience, /Share Live Vibe/);
  });

  it("opens viewer with opaque group_key only", () => {
    assert.match(viewer, /fetchStoryGroup\(key\)/);
    assert.match(experience, /setViewerGroupKey\(group\.group_key\)/);
    assert.doesNotMatch(viewer, /group_key\.split|atob\(|Buffer\.from/);
  });

  it("records views after display delay and avoids duplicate session posts", () => {
    assert.match(viewer, /VIEW_RECORD_DELAY_MS/);
    assert.match(viewer, /recordedRef/);
    assert.match(viewer, /recordStoryView/);
  });

  it("supports hold-to-pause and AppState pause", () => {
    assert.match(viewer, /setHoldPaused\(true\)/);
    assert.match(viewer, /setAppInactive/);
    assert.match(viewer, /AppState\.addEventListener/);
    assert.match(viewer, /onLongPress/);
  });

  it("gates report/delete on eligibility fields", () => {
    assert.match(viewer, /can_report/);
    assert.match(viewer, /can_delete/);
    assert.match(viewer, /STORY_REPORT_REASONS/);
    assert.match(viewer, /deleteStory/);
  });

  it("composer uses verified venue and attribution modes", () => {
    assert.match(composer, /Posting at \{venueName\}/);
    assert.match(composer, /attributionMode: attribution/);
    assert.match(composer, /story-composer-attr-\$\{mode\}/);
    assert.match(composer, /\["attributed", "With your profile"\]/);
    assert.match(composer, /\["anonymous", "Anonymous"\]/);
    assert.match(composer, /idempotencyKey/);
    assert.match(composer, /idempotencyKeyRef/);
    assert.match(api, /Idempotency-Key/);
  });

  it("reuses signed PUT upload helper and polls status", () => {
    assert.match(composer, /uploadFileViaFileSystem/);
    assert.match(composer, /completeUserStoryUpload/);
    assert.match(composer, /fetchStoryUploadStatus/);
    assert.doesNotMatch(composer, /createMediaUpload/);
  });

  it("never logs signed URLs in schema failures", () => {
    const schemas = read("src/features/stories/storySchemas.ts");
    assert.match(schemas, /Never log response bodies/);
    assert.doesNotMatch(schemas, /console\.(log|warn|error)\([^\)]*JSON\.stringify/);
  });

  it("official posts render on venue detail with safe CTA", () => {
    assert.match(venue, /OfficialPostsSection/);
    assert.match(posts, /isSafeExternalCtaUrl/);
    assert.match(posts, /openBrowserAsync/);
    assert.doesNotMatch(posts, /WebView/);
    assert.match(posts, /publication_status === "published"/);
  });

  it("clears Story caches and pending upload on logout", () => {
    assert.match(auth, /"stories"/);
    assert.match(auth, /"official-posts"/);
    assert.match(auth, /clearPendingStoryUpload/);
  });

  it("rail communicates viewed state beyond ring color", () => {
    assert.match(rail, /accessibilityLabel=\{storyGroupAccessibilityLabel/);
    assert.match(rail, /Unviewed/);
    assert.match(rail, /Viewed/);
    assert.match(rail, /Official/);
    assert.match(rail, /group_type === "anon"/);
  });

  it("keeps Live Vibe upload path intact", () => {
    assert.match(experience, /createMediaUpload/);
    assert.match(experience, /pickImageFromLibrary/);
    assert.match(experience, /Live Vibe published/);
    assert.equal(existsSync(path.join(mobileRoot, "assets/fixtures/sample-vibe.jpg")), true);
  });
});
