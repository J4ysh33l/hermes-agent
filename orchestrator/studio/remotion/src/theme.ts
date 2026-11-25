// A profile's look and feel (theme, motion, captions), read by every scene through useProfile().
// video.py writes the page's profile into props.json; DEFAULT_PROFILE is the neutral "dev dark" look.
import "@fontsource/anton/400.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/800.css";
import "@fontsource/inter/900.css";
import "@fontsource/inter-tight/600.css";
import "@fontsource/inter-tight/700.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/montserrat/700.css";
import "@fontsource/montserrat/900.css";
import React, {createContext, useContext} from "react";

export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

export const FONTS = {
  inter: "Inter, sans-serif",
  intertight: "'Inter Tight', Inter, sans-serif",
  montserrat: "Montserrat, sans-serif",
  anton: "Anton, sans-serif",
  jetbrains: "'JetBrains Mono', monospace",
} as const;

export interface Theme {
  bg: string;
  glow: string;
  panel: string;
  text: string;
  muted: string;
  accent: string;
  cool: string;
  bad: string;
  good: string;
  font: keyof typeof FONTS;
  mono: keyof typeof FONTS;
  background: "glow-grid" | "glow" | "flat";
}

export type Enter = "pop" | "rise" | "slide" | "drop" | "zoom" | "fade" | "mask";
export type Exit = "lift" | "fade" | "whip" | "zoom" | "cut";
export type Feel = "snappy" | "soft" | "bouncy" | "settle";
export type Transition = "none" | "cut" | "fade" | "push" | "whip" | "zoom" | "flash" | "burn";

export interface Motion {
  feel: Feel; // spring character for every entrance
  enter: Enter; // default entrance of a scene and its parts
  exit: Exit; // default way a scene leaves
  exit_frames: number;
  punch: number; // camera punch-in on *emphasised* words (0.08 = 8%)
  drift: number; // slow push over each scene (0.04 = 4%)
  step: number; // 0 = smooth; 12 = graphics move at 12 fps (handmade, Vox-like)
  transition: Transition; // scene to scene, the two overlapping; "none" = exit, then entrance
  transition_frames: number;
}

export interface CaptionStyle {
  words: number; // most words on screen at once
  size: number; // px
  upper: boolean;
  font: keyof typeof FONTS;
  stroke: number; // px of outline
  fill: string; // words not being said
  outline: string; // outline and shadow colour
}

export interface Profile {
  name: string;
  theme: Theme;
  motion: Motion;
  captions: CaptionStyle;
}

export const DEFAULT_PROFILE: Profile = {
  name: "default",
  theme: {
    bg: "#0b0f19", glow: "#18223d", panel: "#141a2b", text: "#f5f7fb", muted: "#9aa4bf",
    accent: "#ffd23f", cool: "#4cc9f0", bad: "#ff5d73", good: "#3ddc97",
    font: "inter", mono: "jetbrains", background: "glow-grid",
  },
  motion: {feel: "snappy", enter: "pop", exit: "lift", exit_frames: 5, punch: 0.08, drift: 0.04, step: 0,
    transition: "push", transition_frames: 8},
  captions: {words: 3, size: 92, upper: true, font: "inter", stroke: 14, fill: "#f5f7fb", outline: "#000000"},
};

// Platform buttons and titles cover the top ~12% and bottom ~20% of a vertical video.
export const SAFE = {top: 230, bottom: 400, side: 90};

const Ctx = createContext<Profile>(DEFAULT_PROFILE);

export const ProfileProvider: React.FC<{profile: Profile; children: React.ReactNode}> = ({profile, children}) =>
  React.createElement(Ctx.Provider, {value: profile}, children);

export const useProfile = () => useContext(Ctx);

// Theme with font names resolved to CSS families: what scenes draw with.
export const useTheme = () => {
  const {theme} = useProfile();
  return {...theme, sans: FONTS[theme.font], monoFamily: FONTS[theme.mono]};
};
