// Neutral Fireship-like theme until there is a brand kit: dark ground, one loud accent, one cool accent.
import "@fontsource/inter/600.css";
import "@fontsource/inter/800.css";
import "@fontsource/inter/900.css";
import "@fontsource/jetbrains-mono/500.css";

export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

export const theme = {
  bg: "#0b0f19",
  bgGlow: "#18223d",
  panel: "#141a2b",
  text: "#f5f7fb",
  muted: "#9aa4bf",
  accent: "#ffd23f",
  cool: "#4cc9f0",
  bad: "#ff5d73",
  good: "#3ddc97",
  sans: "Inter, sans-serif",
  mono: "'JetBrains Mono', monospace",
  // Platform buttons and titles cover the top ~12% and bottom ~20% of a vertical video.
  safeTop: 230,
  safeBottom: 400,
  side: 90,
};

// Springs: snappy entrances that settle without wobble.
export const POP = {damping: 14, stiffness: 180, mass: 0.6};
export const SOFT = {damping: 20, stiffness: 120, mass: 0.8};
