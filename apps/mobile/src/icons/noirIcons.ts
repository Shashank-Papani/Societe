/**
 * Centralized Société noir icon requires — static paths only (Metro).
 * Assets live under apps/mobile/assets/icons/noir/png/{tone}/48/.
 */

export const noirIcons = {
  settingsWhite: require("../../assets/icons/noir/png/white/48/settings.png"),
  searchMuted: require("../../assets/icons/noir/png/muted/48/search.png"),
  chevronDownLime: require("../../assets/icons/noir/png/lime/48/chevron-down.png"),
  locationPinLime: require("../../assets/icons/noir/png/lime/48/location-pin.png"),
  heartOutlineWhite: require("../../assets/icons/noir/png/white/48/heart-outline.png"),
  heartFilledLime: require("../../assets/icons/noir/png/lime/48/heart-filled.png"),

  discoverLime: require("../../assets/icons/noir/png/lime/48/discover.png"),
  discoverMuted: require("../../assets/icons/noir/png/muted/48/discover.png"),
  discoverWhite: require("../../assets/icons/noir/png/white/48/discover.png"),

  presenceLime: require("../../assets/icons/noir/png/lime/48/presence.png"),
  presenceMuted: require("../../assets/icons/noir/png/muted/48/presence.png"),

  experienceLime: require("../../assets/icons/noir/png/lime/48/experience.png"),
  experienceMuted: require("../../assets/icons/noir/png/muted/48/experience.png"),

  connectLime: require("../../assets/icons/noir/png/lime/48/connect.png"),
  connectMuted: require("../../assets/icons/noir/png/muted/48/connect.png"),

  profileLime: require("../../assets/icons/noir/png/lime/48/profile.png"),
  profileMuted: require("../../assets/icons/noir/png/muted/48/profile.png"),

  notificationsWhite: require("../../assets/icons/noir/png/white/48/notifications.png"),
  notificationsLime: require("../../assets/icons/noir/png/lime/48/notifications.png"),
  notificationsMuted: require("../../assets/icons/noir/png/muted/48/notifications.png"),
} as const;

export type NoirIconKey = keyof typeof noirIcons;
