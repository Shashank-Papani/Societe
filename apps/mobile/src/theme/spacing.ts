/** 4-point spacing scale. */
export const spacing = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
  xxxl: 40,
} as const;

/** Screen horizontal padding baseline (390pt iPhone). */
export const screenPadding = {
  compact: 14,
  default: 16,
  comfortable: 20,
} as const;

export const radii = {
  small: 10,
  medium: 14,
  large: 18,
  card: 22,
  modal: 26,
  pill: 999,
} as const;

export const motion = {
  pressScale: 0.98,
  bannerMs: 200,
  modalMs: 260,
  cardMs: 200,
} as const;
