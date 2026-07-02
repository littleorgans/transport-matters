/**
 * The transport-matters theme model. A theme is everything a user can change
 * about the app surface: background scene (+ its params), accent, and pane
 * surface treatment. Applied exclusively through CSS custom properties (the
 * production token system) plus the ambient background API, so this file is
 * the exact shape a production Theme panel would ship with.
 */
import {
  ACCENTS,
  accentCss,
  BORDERS,
  type BorderId,
  CORNERS,
  type CornerId,
  type OklchAccent,
  SHADOWS,
  type ShadowId,
  type ThemeAccent,
  type ThemeSettings,
} from "./types";

export type { BorderId, CornerId, ShadowId, ThemeAccent, ThemeSettings };
export { ACCENTS, BORDERS, CORNERS, SHADOWS };

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

const srgbChannel = (linear: number) => {
  const value = clamp01(linear);
  const encoded = value <= 0.0031308 ? 12.92 * value : 1.055 * value ** (1 / 2.4) - 0.055;
  return Math.round(clamp01(encoded) * 255);
};

const oklchToRgb = ({ l, c, h }: OklchAccent) => {
  const hue = (h * Math.PI) / 180;
  const a = Math.cos(hue) * c;
  const b = Math.sin(hue) * c;
  const lPrime = l + 0.3963377774 * a + 0.2158037573 * b;
  const mPrime = l - 0.1055613458 * a - 0.0638541728 * b;
  const sPrime = l - 0.0894841775 * a - 1.291485548 * b;
  const long = lPrime ** 3;
  const medium = mPrime ** 3;
  const short = sPrime ** 3;

  return [
    srgbChannel(4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short),
    srgbChannel(-1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short),
    srgbChannel(-0.0041960863 * long - 0.7034186147 * medium + 1.707614701 * short),
  ] as const;
};

const accentRgb = (accent: ThemeAccent): string => {
  if ("id" in accent) return ACCENTS[accent.id].rgb;
  return oklchToRgb(accent.oklch).join(" ");
};

/**
 * Writes the theme into the production token system. Every reader of these
 * custom properties updates live: panes, command bar, and the Theme panel.
 */
export const applyThemeTokens = (settings: ThemeSettings) => {
  const root = document.documentElement.style;

  root.setProperty("--color-accent", accentCss(settings.accent));
  root.setProperty("--accent-rgb", accentRgb(settings.accent));
  root.setProperty("--pane-radius", `${CORNERS[settings.cornerId].px}px`);
  root.setProperty("--pane-surface-alpha", String(settings.veil));
  root.setProperty("--pane-border-color", BORDERS[settings.borderId].color);
  root.setProperty(
    "--pane-blur",
    settings.glass ? `blur(${settings.glassAmount}px) saturate(120%)` : "none",
  );
  root.setProperty("--pane-shadow", SHADOWS[settings.shadowId].value);
};
