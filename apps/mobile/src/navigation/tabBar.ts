/**
 * Shared Instagram-style tab bar metrics for Société’s five-tab shell.
 */

export const TAB_CONTENT_HEIGHT = 50;
/** Breathing room above the tab bar for scrollable screen content. */
export const TAB_BAR_BREATHING_ROOM = 16;

export const TAB_BAR_BACKGROUND = "#000000";
export const TAB_BAR_BORDER = "rgba(255,255,255,0.10)";
export const TAB_ICON_SIZE = 24;
export const TAB_ACTIVE_COLOR = "#B9F908";
export const TAB_INACTIVE_COLOR = "#8FA39D";

export function tabBarTotalHeight(bottomInset: number): number {
  return TAB_CONTENT_HEIGHT + Math.max(bottomInset, 0);
}

/** Bottom content padding so lists clear the tab bar. */
export function tabScreenBottomPadding(bottomInset: number): number {
  return tabBarTotalHeight(bottomInset) + TAB_BAR_BREATHING_ROOM;
}
